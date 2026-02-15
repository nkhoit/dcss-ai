#!/usr/bin/env python3
"""DCSS AI Driver - Uses configurable LLM providers to autonomously play DCSS.

This script runs in a loop:
1. Reads system prompt + learnings from files
2. Creates a new LLM session with combined context
3. Registers DCSS game tools
4. Lets the AI play until game over (death or win)
5. Cleans up session and loops again

Each game is one session - fresh context but persistent learnings.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time as _time
from pathlib import Path
from typing import Optional

from dcss_ai.game import DCSSGame
from dcss_ai.tools import build_tools
from dcss_ai.providers import get_provider
from dcss_ai.providers.base import LLMProvider, LLMSession
from dcss_ai.config import load_config, DEFAULTS


class DCSSDriver:
    """Main driver that manages LLM sessions and DCSS games."""

    def __init__(self, config):
        self.config = config
        self.running = True
        self.provider: Optional[LLMProvider] = None
        self.dcss = DCSSGame()
        self.total_usage = {
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "premium_requests": 0, "api_calls": 0,
            "total_duration_ms": 0,
        }

        # Set narrate interval for game.py to read
        os.environ["DCSS_NARRATE_INTERVAL"] = str(config["narrate_interval"])

        logging.basicConfig(
            level=logging.DEBUG if config.get("debug") else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        # Silence noisy third-party loggers even in debug mode
        logging.getLogger("websockets").setLevel(logging.INFO)
        logging.getLogger("copilot").setLevel(logging.INFO)
        self.logger = logging.getLogger(__name__)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self._loop = None
        self._shutdown = False
        self._active_session = None

    def _signal_handler(self, signum, frame):
        print(f"\n[Signal {signum}] Shutting down...", flush=True)
        self.running = False
        self._shutdown = True
        # Signal the active session to stop
        if self._active_session and hasattr(self._active_session, '_shutdown'):
            self._active_session._shutdown = True

    def _check_consolidation(self):
        """Check if it's time to recommend learning consolidation."""
        import re
        learnings_path = Path(__file__).parent.parent / "learnings.md"
        if learnings_path.exists():
            content = learnings_path.read_text()
            death_count = len(re.findall(r'### Death #\d+', content))
            if death_count > 0 and death_count % 10 == 0:
                self.logger.info(f"Consolidation recommended after {death_count} deaths")

    async def connect_to_dcss(self) -> bool:
        """Connect to DCSS server."""
        try:
            self.logger.info(f"Connecting to DCSS server at {self.config["server_url"]}")
            self.dcss.connect(self.config["server_url"], self.config["username"], self.config["password"])
            self.logger.info("Connected to DCSS server")
            return True
        except Exception as e:
            self.logger.error(f"DCSS connection error: {e}")
            return False

    def load_system_prompt(self) -> str:
        """Load system prompt from file and append learnings."""
        prompt_path = Path(__file__).parent.parent / "system_prompt.md"
        with open(prompt_path, 'r') as f:
            system_prompt = f.read()

        learnings_path = Path(__file__).parent.parent / "learnings.md"
        if learnings_path.exists():
            with open(learnings_path, 'r') as f:
                learnings = f.read()
            system_prompt += f"\n\n---\n\n## Your Accumulated Learnings\n\n{learnings}"

        return system_prompt

    async def run_game_session(self) -> None:
        """Run one complete game as a single LLM session."""
        system_prompt = self.load_system_prompt()
        tools = build_tools(self.dcss)

        session = await self.provider.create_session(system_prompt, tools, self.config["model"])
        self._active_session = session

        # Track tool activity to detect hangs
        SILENT_TIMEOUT = self.config["silent_timeout"]
        MAX_RETRIES = self.config["max_retries"]

        kickoff_prompt = (
            "Start a new DCSS game. Call new_attempt() first, then start_game(). "
            "Try a different species/background combo than last time — experiment! "
            "Then begin exploring. Good luck!"
        )

        continue_prompt = (
            "You are autonomous — there is no human to respond. NEVER say 'let me know' or wait for input. "
            "Call get_stats() to check your state, then keep playing. Do NOT stop until the game ends."
        )

        try:
            self.logger.info(f"Starting game session (attempt #{self.dcss._attempt + 1})")
            self.dcss._session_ended = False  # reset for new session
            prompt = kickoff_prompt
            retries = 0
            deaths_before = self.dcss._deaths
            wins_before = self.dcss._wins
            nudge_count = 0  # consecutive SDK completions without tool calls

            while self.running and retries < MAX_RETRIES:
                session.last_tool_time = _time.time()
                session.last_delta_time = _time.time()
                self.logger.info("Sending prompt to LLM...")

                try:
                    result = await session.send(prompt)
                    
                    if result.completed:
                        # SDK thinks it's done — but check if the game actually ended
                        if self.dcss._deaths > deaths_before or self.dcss._wins > wins_before:
                            self.logger.info("Session completed — game ended (death/win)")
                            # Consolidation trigger
                            if self.dcss._deaths > deaths_before:
                                self._check_consolidation()
                            self.logger.info(
                                f"Session usage: {result.usage.get('api_calls', 0)} API calls, "
                                f"{result.usage.get('input_tokens', 0):,} input tokens, "
                                f"{result.usage.get('output_tokens', 0):,} output tokens, "
                                f"{result.usage.get('cache_read_tokens', 0):,} cache read tokens, "
                                f"{result.usage.get('premium_requests', 0)} premium requests, "
                                f"{result.usage.get('total_duration_ms', 0)/1000:.1f}s total API time"
                            )
                            break
                        else:
                            # SDK ended but game is still going — auto-continue (not a retry)
                            nudge_count += 1
                            if nudge_count >= 10:
                                # Session is stuck — create a fresh one
                                self.logger.warning(f"SDK completed {nudge_count}x without progress, creating new session...")
                                session = await self.provider.create_session(system_prompt, tools, self.config["model"])
                                self._active_session = session
                                nudge_count = 0
                                retries += 1
                                prompt = (
                                    "You are continuing a game already in progress. "
                                    "Call get_stats() and get_state_text() to see your current state, then keep playing."
                                )
                            else:
                                self.logger.info(f"SDK session completed, game still active — nudging ({nudge_count})...")
                                prompt = (
                                    "The game is still in progress. You are autonomous — DO NOT stop playing. "
                                    "DO NOT ask for user input. Call a tool and keep going."
                                )
                            continue
                    else:
                        # Timeout or other failure
                        # Check if a game ended during this turn
                        if self.dcss._deaths > deaths_before or self.dcss._wins > wins_before:
                            self.logger.info("Game ended (death/win detected), ending session")
                            if self.dcss._deaths > deaths_before:
                                self._check_consolidation()
                            break

                        elapsed_since_tool = _time.time() - session.last_tool_time
                        elapsed_since_delta = _time.time() - session.last_delta_time
                        
                        if elapsed_since_delta > SILENT_TIMEOUT:
                            retries += 1
                            self.logger.warning(
                                f"LLM silent — no output for {elapsed_since_delta:.0f}s "
                                f"(retry {retries}/{MAX_RETRIES})"
                            )
                            prompt = continue_prompt
                        elif elapsed_since_tool > SILENT_TIMEOUT:
                            retries += 1
                            self.logger.warning(
                                f"LLM narrating without tool calls for {elapsed_since_tool:.0f}s "
                                f"(retry {retries}/{MAX_RETRIES})"
                            )
                            prompt = continue_prompt
                        else:
                            # Tool calls happened — it's playing, reset retries and nudges
                            retries = 0
                            nudge_count = 0
                            retries = 0
                            self.logger.info("Game still in progress, continuing...")
                            prompt = continue_prompt
                            
                except Exception as e:
                    self.logger.error(f"Error during LLM interaction: {e}")
                    retries += 1
                    prompt = continue_prompt

            if retries >= MAX_RETRIES:
                self.logger.warning(f"Stuck after {MAX_RETRIES} retries, abandoning THIS game (will start a new one)")
                # Try to cleanly quit the stuck game
                try:
                    self.dcss.quit_game()
                except Exception:
                    pass

            self.logger.info(f"Game session ended. Deaths: {self.dcss._deaths}, Wins: {self.dcss._wins}")

        except Exception as e:
            self.logger.error(f"Error during game session: {e}")
        finally:
            # Accumulate usage from this session's provider
            if session and hasattr(session, 'usage_totals'):
                for k in self.total_usage:
                    self.total_usage[k] += session.usage_totals.get(k, 0)

    async def run_forever(self):
        """Main loop - runs games forever until interrupted."""
        self._loop = asyncio.get_running_loop()
        self.logger.info("Starting DCSS AI Driver")

        # Start overlay SSE server
        from dcss_ai.overlay import start_server as start_sse
        sse_port = self.config.get("overlay_port", 8889)
        sse_server = await start_sse(sse_port)

        # Initialize LLM provider
        self.provider = get_provider(self.config["provider"], 
                                      base_url=self.config.get("base_url"),
                                      api_key=self.config.get("api_key"))
        await self.provider.start()
        self.logger.info(f"LLM provider '{self.config["provider"]}' connected")

        # Connect to DCSS server
        if not await self.connect_to_dcss():
            self.logger.error("Failed to connect to DCSS, exiting")
            await self.provider.stop()
            return 1

        game_count = 0
        start_time = _time.time()

        try:
            while self.running:
                try:
                    game_count += 1
                    self.logger.info(f"=== Game #{game_count} ===")

                    await self.run_game_session()

                    # Brief pause between games
                    if self.running:
                        if self.config["single"]:
                            self.logger.info("Single game mode, exiting")
                            break
                        self.logger.info("Starting next game in 5 seconds...")
                        await asyncio.sleep(5)

                except (KeyboardInterrupt, asyncio.CancelledError):
                    break
                except Exception as e:
                    self.logger.error(f"Error in game loop: {e}")
                    if self.running:
                        self.logger.info("Retrying in 30 seconds...")
                        await asyncio.sleep(30)

                # Reconnect if needed
                if self.running and not self.dcss._connected:
                    self.logger.warning("DCSS connection lost, reconnecting...")
                    await self.connect_to_dcss()

        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        # --- Session summary ---
        elapsed = _time.time() - start_time
        hours, rem = divmod(int(elapsed), 3600)
        mins, secs = divmod(rem, 60)
        print(f"\n{'='*50}")
        print(f"  DCSS AI Driver — Session Summary")
        print(f"{'='*50}")
        print(f"  Games played:  {game_count}")
        print(f"  Deaths:        {self.dcss._deaths}")
        print(f"  Wins:          {self.dcss._wins}")
        print(f"  Runtime:       {hours}h {mins}m {secs}s")
        print(f"  Model:         {self.config["model"]}")
        print(f"  API calls:     {self.total_usage['api_calls']:,}")
        print(f"  Input tokens:  {self.total_usage['input_tokens']:,}")
        print(f"  Output tokens: {self.total_usage['output_tokens']:,}")
        print(f"  Cache read:    {self.total_usage['cache_read_tokens']:,}")
        print(f"  Cache write:   {self.total_usage['cache_write_tokens']:,}")
        print(f"  API time:      {self.total_usage['total_duration_ms']/1000:.1f}s")
        print(f"{'='*50}\n")

        # Clean up game
        try:
            if self.dcss._in_game:
                self.logger.info("Quitting current game...")
                self.dcss.quit_game()
        except Exception:
            pass

        self.dcss.disconnect()
        await self.provider.stop()
        self.logger.info("Driver stopped.")
        return 0


async def main():
    parser = argparse.ArgumentParser(description="DCSS AI Driver with configurable LLM providers")
    parser.add_argument("--server-url", dest="server_url", default=None,
                        help=f"DCSS webtiles WebSocket URL (default: {DEFAULTS['server_url']})")
    parser.add_argument("--username", default=None,
                        help=f"DCSS server username (default: {DEFAULTS['username']})")
    parser.add_argument("--password", default=None,
                        help=f"DCSS server password (default: {DEFAULTS['password']})")
    parser.add_argument("--provider", default=None,
                        help=f"LLM provider (default: {DEFAULTS['provider']})")
    parser.add_argument("--base-url", dest="base_url", default=None,
                        help="Base URL for OpenAI-compatible provider")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="API key for OpenAI-compatible provider")
    parser.add_argument("--model", default=None,
                        help=f"Model to use (default: {DEFAULTS['model']})")
    parser.add_argument("--single", action="store_true", default=False,
                        help="Play one game then exit")
    parser.add_argument("--narrate-interval", dest="narrate_interval", type=int, default=None,
                        help=f"Actions between forced narrations, 0=disable (default: {DEFAULTS['narrate_interval']})")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Enable debug logging (tool calls, etc.)")
    args = parser.parse_args()

    # store_true gives False not None — only override if explicitly set
    cli_dict = {k: v for k, v in vars(args).items() if v is not None}
    if args.single:
        cli_dict["single"] = True
    else:
        cli_dict.pop("single", None)
    if args.debug:
        cli_dict["debug"] = True
    else:
        cli_dict.pop("debug", None)

    config = load_config(cli_dict)
    driver = DCSSDriver(config)
    return await driver.run_forever()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))