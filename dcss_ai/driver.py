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


class DCSSDriver:
    """Main driver that manages LLM sessions and DCSS games."""

    def __init__(self, args):
        self.args = args
        self.running = True
        self.provider: Optional[LLMProvider] = None
        self.dcss = DCSSGame()

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        self.logger = logging.getLogger(__name__)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    async def connect_to_dcss(self) -> bool:
        """Connect to DCSS server."""
        try:
            self.logger.info(f"Connecting to DCSS server at {self.args.server_url}")
            self.dcss.connect(self.args.server_url, self.args.username, self.args.password)
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

        session = await self.provider.create_session(system_prompt, tools, self.args.model)

        # Track tool activity to detect hangs
        SILENT_TIMEOUT = 60  # seconds — no output at all = truly stuck
        MAX_RETRIES = 5     # consecutive timeouts before abandoning THIS game

        kickoff_prompt = (
            "Start a new DCSS game. Call new_attempt() first, then start_game(). "
            "Try a different species/background combo than last time — experiment! "
            "Then begin exploring. Good luck!"
        )

        continue_prompt = (
            "You MUST call a tool now. You went silent without "
            "calling any tool. Call get_state_text() to check the game, then take an action. "
            "Do NOT just narrate — every response needs a tool call. "
            "If the game is over, call record_death() or record_win()."
        )

        try:
            self.logger.info(f"Starting game session (attempt #{self.dcss._attempt + 1})")
            self.dcss._session_ended = False  # reset for new session
            prompt = kickoff_prompt
            retries = 0
            deaths_before = self.dcss._deaths
            wins_before = self.dcss._wins

            while self.running and retries < MAX_RETRIES:
                session.last_tool_time = _time.time()
                session.last_delta_time = _time.time()
                self.logger.info("Sending prompt to LLM...")

                try:
                    result = await session.send(prompt)
                    
                    if result.completed:
                        # Normal completion — game ended
                        self.logger.info("Session completed normally")
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
                        # Timeout or other failure
                        # Check if a game ended during this turn
                        if self.dcss._deaths > deaths_before or self.dcss._wins > wins_before:
                            self.logger.info("Game ended (death/win detected), ending session")
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
                            # Tool calls happened — it's playing, reset retries
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
            # Session cleanup — create a fresh one for next game
            pass

    async def run_forever(self):
        """Main loop - runs games forever until interrupted."""
        self.logger.info("Starting DCSS AI Driver")

        # Initialize LLM provider
        self.provider = get_provider(self.args.provider, 
                                      base_url=getattr(self.args, 'base_url', None),
                                      api_key=getattr(self.args, 'api_key', None))
        await self.provider.start()
        self.logger.info(f"LLM provider '{self.args.provider}' connected")

        # Connect to DCSS server
        if not await self.connect_to_dcss():
            self.logger.error("Failed to connect to DCSS, exiting")
            await self.provider.stop()
            return 1

        game_count = 0

        while self.running:
            try:
                game_count += 1
                self.logger.info(f"=== Game #{game_count} ===")

                await self.run_game_session()

                # Brief pause between games
                if self.running:
                    if self.args.single:
                        self.logger.info("Single game mode, exiting")
                        break
                    self.logger.info("Starting next game in 5 seconds...")
                    await asyncio.sleep(5)

            except Exception as e:
                self.logger.error(f"Error in game loop: {e}")
                if self.running:
                    self.logger.info("Retrying in 30 seconds...")
                    await asyncio.sleep(30)

            # Reconnect if needed
            if self.running and not self.dcss._connected:
                self.logger.warning("DCSS connection lost, reconnecting...")
                await self.connect_to_dcss()

        self.logger.info("Shutting down driver")
        await self.provider.stop()
        return 0


async def main():
    parser = argparse.ArgumentParser(description="DCSS AI Driver with configurable LLM providers")
    parser.add_argument("--server-url", default="ws://localhost:8080/socket",
                        help="DCSS webtiles server WebSocket URL")
    parser.add_argument("--username", default="kurobot",
                        help="DCSS server username")
    parser.add_argument("--password", default="kurobot123",
                        help="DCSS server password")
    parser.add_argument("--provider", default="copilot",
                        help="LLM provider to use (copilot, openai)")
    parser.add_argument("--base-url", default=None,
                        help="Base URL for OpenAI-compatible provider (e.g. https://ollama.example.com/v1)")
    parser.add_argument("--api-key", default=None,
                        help="API key for OpenAI-compatible provider")
    parser.add_argument("--model", default="claude-sonnet-4",
                        help="Model to use")
    parser.add_argument("--single", action="store_true",
                        help="Play one game then exit")
    args = parser.parse_args()

    driver = DCSSDriver(args)
    return await driver.run_forever()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))