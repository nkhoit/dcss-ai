#!/usr/bin/env python3
"""DCSS AI Driver - Uses GitHub Copilot SDK to autonomously play DCSS.

This script runs in a loop:
1. Reads system prompt + learnings from files
2. Creates a new Copilot session with combined context
3. Registers DCSS game tools
4. Lets the AI play until game over (death or win)
5. Cleans up session and loops again

Each game is one session - fresh context but persistent learnings.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from copilot import CopilotClient
from copilot.tools import define_tool
from copilot.generated.session_events import SessionEventType
from pydantic import BaseModel, Field

from dcss_ai.game import DCSSGame


# --- Tool parameter models ---

class EmptyParams(BaseModel):
    pass

class DirectionParams(BaseModel):
    direction: str = Field(description="Direction: n/s/e/w/ne/nw/se/sw")

class SlotParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")

class SlotDirectionParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")
    direction: str = Field(description="Direction: n/s/e/w/ne/nw/se/sw")

class SlotOptionalDirectionParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")
    direction: str = Field(default="", description="Direction: n/s/e/w/ne/nw/se/sw (optional)")

class OptionalSlotParams(BaseModel):
    key: str = Field(default="", description="Inventory slot letter (a-z), optional if only one worn")

class SpellParams(BaseModel):
    key: str = Field(description="Spell slot letter")
    direction: str = Field(default="", description="Direction to cast: n/s/e/w/ne/nw/se/sw (optional)")

class OverlayParams(BaseModel):
    thought: str = Field(default="", description="Brief one-liner about what you're thinking (shown to stream viewers)")

class DeathParams(BaseModel):
    cause: str = Field(default="", description="Brief cause of death")

class LearningParams(BaseModel):
    text: str = Field(description="A lesson learned from this game. Be specific and actionable.")

class StartGameParams(BaseModel):
    species_key: str = Field(default="b", description=(
        "Species key: a=Human, b=Minotaur, c=Merfolk, d=Gargoyle, e=Draconian, "
        "f=Palentonga, g=Gnoll, h=Troll, i=Ghoul, j=Tengu, k=Barachi, "
        "l=Ogre, m=Djinni, n=Spriggan, o=Vine Stalker, p=Demigod, "
        "q=Demonspawn, r=Mummy, s=Naga, t=Formicid, u=Kobold, v=Vampire, "
        "w=Deep Elf, x=Hill Orc, y=Octopode, z=Felid"
    ))
    background_key: str = Field(default="f", description=(
        "Background key: a=Fighter, b=Gladiator, c=Monk, d=Hunter, e=Brigand, "
        "f=Berserker, g=Cinder Acolyte, h=Chaos Knight, i=Wanderer, "
        "j=Wizard, k=Conjurer, l=Summoner, m=Necromancer, n=Transmuter, "
        "o=Fire Elementalist, p=Ice Elementalist, q=Air Elementalist, "
        "r=Earth Elementalist, s=Venom Mage, t=Enchanter, u=Hexslinger, "
        "v=Warper, w=Alchemist"
    ))
    weapon_key: str = Field(default="b", description="Weapon key (a or b, depends on background)")

class MapParams(BaseModel):
    radius: int = Field(default=7, description="Map view radius")

class MessagesParams(BaseModel):
    n: int = Field(default=10, description="Number of recent messages to return")


def build_dcss_tools(dcss: DCSSGame) -> list:
    """Build all DCSS tool definitions for the Copilot SDK."""

    # --- State queries (free, no turn cost) ---

    @define_tool(description="Get full game state: stats, messages, inventory, enemies, map. Use this to orient yourself.")
    def get_state_text(params: EmptyParams) -> str:
        return dcss.get_state_text()

    @define_tool(description="Get ASCII map centered on player (@). Radius controls view size.")
    def get_map(params: MapParams) -> str:
        return dcss.get_map(radius=params.radius)

    @define_tool(description="Get inventory as list of items with slot letters and names.")
    def get_inventory(params: EmptyParams) -> str:
        return json.dumps(dcss.get_inventory(), indent=2)

    @define_tool(description="Get nearby visible enemies sorted by distance, with direction and threat level.")
    def get_nearby_enemies(params: EmptyParams) -> str:
        return json.dumps(dcss.get_nearby_enemies(), indent=2)

    @define_tool(description="Get one-line stats summary: HP, MP, AC, EV, XL, place, turn.")
    def get_stats(params: EmptyParams) -> str:
        return dcss.get_stats()

    @define_tool(description="Get last N game messages. Messages reveal what's happening in combat.")
    def get_messages(params: MessagesParams) -> str:
        return "\n".join(dcss.get_messages(n=params.n))

    # --- Movement & exploration ---

    @define_tool(description="Move one step in a direction. Moving into an enemy = melee attack.")
    def move(params: DirectionParams) -> str:
        msgs = dcss.move(params.direction)
        return "\n".join(msgs) if msgs else "Moved."

    @define_tool(description="Auto-explore the current floor. Stops on enemies, items, or fully explored.")
    def auto_explore(params: EmptyParams) -> str:
        msgs = dcss.auto_explore()
        return "\n".join(msgs) if msgs else "Exploring..."

    @define_tool(description="Auto-fight nearest enemy (Tab). Blocked at low HP as Berserker — use attack() instead.")
    def auto_fight(params: EmptyParams) -> str:
        msgs = dcss.auto_fight()
        return "\n".join(msgs) if msgs else "Fighting..."

    @define_tool(description="Rest until healed (5). Won't work with enemies nearby.")
    def rest(params: EmptyParams) -> str:
        msgs = dcss.rest()
        return "\n".join(msgs) if msgs else "Resting..."

    @define_tool(description="Wait one turn in place.")
    def wait_turn(params: EmptyParams) -> str:
        msgs = dcss.wait_turn()
        return "\n".join(msgs) if msgs else "Waited."

    @define_tool(description="Go upstairs (<).")
    def go_upstairs(params: EmptyParams) -> str:
        msgs = dcss.go_upstairs()
        return "\n".join(msgs) if msgs else "Went upstairs."

    @define_tool(description="Go downstairs (>).")
    def go_downstairs(params: EmptyParams) -> str:
        msgs = dcss.go_downstairs()
        return "\n".join(msgs) if msgs else "Went downstairs."

    # --- Items ---

    @define_tool(description="Pick up items on the ground.")
    def pickup(params: EmptyParams) -> str:
        msgs = dcss.pickup()
        return "\n".join(msgs) if msgs else "Picked up."

    @define_tool(description="Wield a weapon by inventory slot letter.")
    def wield(params: SlotParams) -> str:
        msgs = dcss.wield(params.key)
        return "\n".join(msgs) if msgs else "Wielded."

    @define_tool(description="Wear armour by inventory slot letter.")
    def wear(params: SlotParams) -> str:
        msgs = dcss.wear(params.key)
        return "\n".join(msgs) if msgs else "Wearing."

    @define_tool(description="Drink a potion by inventory slot letter.")
    def quaff(params: SlotParams) -> str:
        msgs = dcss.quaff(params.key)
        return "\n".join(msgs) if msgs else "Quaffed."

    @define_tool(description="Read a scroll by inventory slot letter.")
    def read_scroll(params: SlotParams) -> str:
        msgs = dcss.read_scroll(params.key)
        return "\n".join(msgs) if msgs else "Read scroll."

    @define_tool(description="Drop an item by inventory slot letter.")
    def drop(params: SlotParams) -> str:
        msgs = dcss.drop(params.key)
        return "\n".join(msgs) if msgs else "Dropped."

    @define_tool(description="Zap a wand by inventory slot letter, optionally in a direction.")
    def zap_wand(params: SlotOptionalDirectionParams) -> str:
        msgs = dcss.zap_wand(params.key, params.direction)
        return "\n".join(msgs) if msgs else "Zapped."

    @define_tool(description="Evoke a miscellaneous evocable item by inventory slot letter.")
    def evoke(params: SlotParams) -> str:
        msgs = dcss.evoke(params.key)
        return "\n".join(msgs) if msgs else "Evoked."

    @define_tool(description="Throw/fire an item at an enemy. Requires slot letter and direction.")
    def throw_item(params: SlotDirectionParams) -> str:
        msgs = dcss.throw_item(params.key, params.direction)
        return "\n".join(msgs) if msgs else "Thrown."

    @define_tool(description="Put on a ring or amulet by inventory slot letter.")
    def put_on_jewelry(params: SlotParams) -> str:
        msgs = dcss.put_on_jewelry(params.key)
        return "\n".join(msgs) if msgs else "Put on."

    @define_tool(description="Remove a ring or amulet. Slot letter optional if only one worn.")
    def remove_jewelry(params: OptionalSlotParams) -> str:
        msgs = dcss.remove_jewelry(params.key)
        return "\n".join(msgs) if msgs else "Removed."

    @define_tool(description="Take off worn armour by inventory slot letter.")
    def take_off_armour(params: SlotParams) -> str:
        msgs = dcss.take_off_armour(params.key)
        return "\n".join(msgs) if msgs else "Taken off."

    @define_tool(description="Examine/describe an inventory item by slot letter. Shows stats and details.")
    def examine(params: SlotParams) -> str:
        msgs = dcss.examine(params.key)
        return "\n".join(msgs) if msgs else "No description."

    # --- Combat & abilities ---

    @define_tool(description="Melee attack in a direction. Use when auto_fight is blocked at low HP.")
    def attack(params: DirectionParams) -> str:
        msgs = dcss.attack(params.direction)
        return "\n".join(msgs) if msgs else "Attacked."

    @define_tool(description="Use a god/species ability by key. a=Berserk, b=Trog's Hand, c=Brothers in Arms.")
    def use_ability(params: SlotParams) -> str:
        msgs = dcss.use_ability(params.key)
        return "\n".join(msgs) if msgs else "Used ability."

    @define_tool(description="Cast a spell by key, optionally in a direction.")
    def cast_spell(params: SpellParams) -> str:
        msgs = dcss.cast_spell(params.key, params.direction)
        return "\n".join(msgs) if msgs else "Cast spell."

    @define_tool(description="Pray at an altar.")
    def pray(params: EmptyParams) -> str:
        msgs = dcss.pray()
        return "\n".join(msgs) if msgs else "Prayed."

    # --- Interface ---

    @define_tool(description="Confirm a prompt (Y).")
    def confirm(params: EmptyParams) -> str:
        msgs = dcss.confirm()
        return "\n".join(msgs) if msgs else "Confirmed."

    @define_tool(description="Deny a prompt (N).")
    def deny(params: EmptyParams) -> str:
        msgs = dcss.deny()
        return "\n".join(msgs) if msgs else "Denied."

    @define_tool(description="Press Escape to cancel.")
    def escape(params: EmptyParams) -> str:
        msgs = dcss.escape()
        return "\n".join(msgs) if msgs else "Escaped."

    # --- Overlay & stats ---

    @define_tool(description="Update the stream overlay with current stats and your thought. Call after every action.")
    def update_overlay(params: OverlayParams) -> str:
        dcss.update_overlay(params.thought)
        return "Overlay updated."

    @define_tool(description="Start a new game attempt. Call before start_game. Increments attempt counter on overlay.")
    def new_attempt(params: EmptyParams) -> str:
        dcss.new_attempt()
        return f"Attempt #{dcss._attempt} started."

    @define_tool(description="Record a death. Call when you die. Increments death counter.")
    def record_death(params: DeathParams) -> str:
        dcss.record_death(params.cause)
        return f"Death #{dcss._deaths} recorded."

    @define_tool(description="Record a win. Call when you escape with the Orb.")
    def record_win(params: EmptyParams) -> str:
        dcss.record_win()
        return f"Win #{dcss._wins} recorded!"

    # --- Learnings ---

    learnings_path = Path(__file__).parent.parent / "learnings.md"

    @define_tool(description="Append a lesson to learnings.md. Call after every death AND every win. Be specific: what happened, why, what to do differently. These persist across all future games.")
    def write_learning(params: LearningParams) -> str:
        with open(learnings_path, 'a') as f:
            f.write(f"\n- {params.text}")
        return "Learning recorded."

    # --- Game lifecycle ---

    @define_tool(description="Start a new DCSS game. Default: Minotaur Berserker (species=b, bg=f, weapon=b). Abandons any existing save first.")
    def start_game(params: StartGameParams) -> str:
        return dcss.start_game(params.species_key, params.background_key, params.weapon_key)

    return [
        get_state_text, get_map, get_inventory, get_nearby_enemies,
        get_stats, get_messages,
        move, auto_explore, auto_fight, rest, wait_turn,
        go_upstairs, go_downstairs,
        pickup, wield, wear, quaff, read_scroll, drop,
        zap_wand, evoke, throw_item, put_on_jewelry, remove_jewelry,
        take_off_armour, examine,
        attack, use_ability, cast_spell, pray,
        confirm, deny, escape, 
        update_overlay, new_attempt, record_death, record_win,
        write_learning,
        start_game,
    ]


class DCSSDriver:
    """Main driver that manages Copilot sessions and DCSS games."""

    def __init__(self, args):
        self.args = args
        self.running = True
        self.client: Optional[CopilotClient] = None
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
        """Run one complete game as a single Copilot session."""
        system_prompt = self.load_system_prompt()
        tools = build_dcss_tools(self.dcss)

        session = await self.client.create_session({
            "model": self.args.model,
            "system_message": system_prompt,
            "tools": tools,
            "streaming": True,
            "available_tools": [],  # disable built-in tools (filesystem, git, etc)
            "infinite_sessions": {
                "enabled": True,  # let the SDK handle context management
            },
        })

        # Track tool activity to detect hangs
        last_tool_call = [0.0]  # mutable ref for closure
        import time as _time

        # Accumulate usage stats
        usage_totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                        "cache_write_tokens": 0, "premium_requests": 0, "api_calls": 0,
                        "total_duration_ms": 0}

        def handle_event(event):
            if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                content = event.data.delta_content
                if content and content.strip():
                    sys.stdout.write(content)
                    sys.stdout.flush()
            elif event.type == SessionEventType.ASSISTANT_MESSAGE:
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif event.type in (SessionEventType.TOOL_EXECUTION_START, SessionEventType.TOOL_EXECUTION_COMPLETE):
                last_tool_call[0] = _time.time()
            elif event.type == SessionEventType.ASSISTANT_USAGE:
                d = event.data
                usage_totals["input_tokens"] += int(d.input_tokens or 0)
                usage_totals["output_tokens"] += int(d.output_tokens or 0)
                usage_totals["cache_read_tokens"] += int(d.cache_read_tokens or 0)
                usage_totals["cache_write_tokens"] += int(d.cache_write_tokens or 0)
                usage_totals["premium_requests"] += int(d.cost or 0)
                usage_totals["api_calls"] += 1
                usage_totals["total_duration_ms"] += int(d.duration or 0)

        session.on(handle_event)

        TURN_TIMEOUT = 120  # seconds — max time to wait for a tool call
        MAX_RETRIES = 3     # consecutive timeouts before giving up

        kickoff_prompt = (
            "Start a new DCSS game. Call new_attempt() first, then start_game(). "
            "Try a different species/background combo than last time — experiment! "
            "Then begin exploring. Good luck!"
        )

        continue_prompt = (
            "Continue playing. You stopped responding — check the game state with "
            "get_state_text() and keep going. If the game is over, call record_death() "
            "or record_win(), write_learning(), and say GAME_OVER."
        )

        try:
            self.logger.info(f"Starting game session (attempt #{self.dcss._attempt + 1})")
            prompt = kickoff_prompt
            retries = 0

            while self.running and retries < MAX_RETRIES:
                last_tool_call[0] = _time.time()
                self.logger.info("Sending prompt to LLM...")

                try:
                    await asyncio.wait_for(
                        session.send_and_wait({"prompt": prompt}, timeout=7200),
                        timeout=TURN_TIMEOUT
                    )
                    # Normal completion — game ended
                    break
                except asyncio.TimeoutError:
                    elapsed = _time.time() - last_tool_call[0]
                    if elapsed > TURN_TIMEOUT * 0.8:
                        # No tool calls during the timeout — SDK is hung
                        retries += 1
                        self.logger.warning(
                            f"LLM hung — no tool calls for {elapsed:.0f}s "
                            f"(retry {retries}/{MAX_RETRIES})"
                        )
                        prompt = continue_prompt
                    else:
                        # Tool calls happened but send_and_wait didn't finish
                        # — game is still going, just long-running
                        retries = 0
                        self.logger.info("Game still in progress, continuing...")
                        prompt = continue_prompt

            if retries >= MAX_RETRIES:
                self.logger.error(f"LLM hung {MAX_RETRIES} times in a row, abandoning game")

            self.logger.info(f"Game session ended. Deaths: {self.dcss._deaths}, Wins: {self.dcss._wins}")
            self.logger.info(
                f"Session usage: {usage_totals['api_calls']} API calls, "
                f"{usage_totals['input_tokens']:,} input tokens, "
                f"{usage_totals['output_tokens']:,} output tokens, "
                f"{usage_totals['cache_read_tokens']:,} cache read tokens, "
                f"{usage_totals['premium_requests']} premium requests, "
                f"{usage_totals['total_duration_ms']/1000:.1f}s total API time"
            )

        except Exception as e:
            self.logger.error(f"Error during game session: {e}")
        finally:
            # Session cleanup — create a fresh one for next game
            pass

    async def run_forever(self):
        """Main loop - runs games forever until interrupted."""
        self.logger.info("Starting DCSS AI Driver")

        # Initialize Copilot client
        self.client = CopilotClient()
        await self.client.start()
        self.logger.info("Copilot SDK connected")

        # Connect to DCSS server
        if not await self.connect_to_dcss():
            self.logger.error("Failed to connect to DCSS, exiting")
            await self.client.stop()
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
        await self.client.stop()
        return 0


async def main():
    parser = argparse.ArgumentParser(description="DCSS AI Driver using GitHub Copilot SDK")
    parser.add_argument("--server-url", default="ws://localhost:8080/socket",
                        help="DCSS webtiles server WebSocket URL")
    parser.add_argument("--username", default="kurobot",
                        help="DCSS server username")
    parser.add_argument("--password", default="kurobot123",
                        help="DCSS server password")
    parser.add_argument("--model", default="claude-sonnet-4",
                        help="Copilot model to use")
    parser.add_argument("--single", action="store_true",
                        help="Play one game then exit")
    args = parser.parse_args()

    driver = DCSSDriver(args)
    return await driver.run_forever()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
