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

# TODO: Verify exact import path when GitHub Copilot SDK is available
# from copilot import CopilotClient
from dcss_ai.game import DCSSGame


class DCSSDriver:
    """Main driver that manages Copilot sessions and DCSS games."""
    
    def __init__(self, args):
        self.args = args
        self.running = True
        self.client = None  # CopilotClient instance
        self.dcss = DCSSGame()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        self.logger = logging.getLogger(__name__)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Graceful shutdown on SIGINT/SIGTERM."""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        if self.client:
            # TODO: Implement proper client shutdown when SDK is available
            pass
    
    async def connect_to_dcss(self):
        """Connect to DCSS server."""
        try:
            self.logger.info(f"Connecting to DCSS server at {self.args.server_url}")
            success = self.dcss.connect(self.args.server_url, self.args.username, self.args.password)
            if success:
                self.logger.info("Successfully connected to DCSS server")
                return True
            else:
                self.logger.error("Failed to connect to DCSS server")
                return False
        except Exception as e:
            self.logger.error(f"DCSS connection error: {e}")
            return False
    
    def load_system_prompt(self) -> str:
        """Load system prompt from file and append learnings."""
        try:
            prompt_path = Path(__file__).parent / "system_prompt.md"
            with open(prompt_path, 'r') as f:
                system_prompt = f.read()
            
            # Append learnings
            learnings_path = Path(__file__).parent.parent / "skill" / "learnings.md"
            if learnings_path.exists():
                with open(learnings_path, 'r') as f:
                    learnings = f.read()
                
                system_prompt += f"\n\n## Previous Learnings\n\n{learnings}"
            else:
                self.logger.warning(f"Learnings file not found at {learnings_path}")
            
            return system_prompt
            
        except Exception as e:
            self.logger.error(f"Failed to load system prompt: {e}")
            raise
    
    async def create_copilot_session(self, system_prompt: str):
        """Create a new Copilot session with the given system prompt."""
        try:
            # TODO: Implement actual Copilot SDK integration when available
            # For now, this is a placeholder structure
            """
            session = await self.client.create_session({
                "model": self.args.model,
                "system_prompt": system_prompt
            })
            
            # Register DCSS tools - TODO: Verify exact API pattern
            dcss_tools = self._get_dcss_tools()
            for tool in dcss_tools:
                await session.register_tool(tool)
            
            return session
            """
            self.logger.warning("Copilot SDK integration not implemented - placeholder session")
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to create Copilot session: {e}")
            raise
    
    def _get_dcss_tools(self) -> list:
        """Return list of DCSS tool definitions for Copilot SDK."""
        # TODO: Define proper tool schemas for the Copilot SDK
        # This should match whatever format the SDK expects
        tools = [
            # Connection & game management
            {"name": "connect", "handler": self.dcss.connect},
            {"name": "start_game", "handler": self.dcss.start_game},
            
            # State queries (free actions)
            {"name": "get_state_text", "handler": self.dcss.get_state_text},
            {"name": "get_map", "handler": self.dcss.get_map},
            {"name": "get_inventory", "handler": self.dcss.get_inventory},
            {"name": "get_nearby_enemies", "handler": self.dcss.get_nearby_enemies},
            {"name": "get_stats", "handler": self.dcss.get_stats},
            {"name": "get_messages", "handler": self.dcss.get_messages},
            
            # Movement & exploration
            {"name": "move", "handler": self.dcss.move},
            {"name": "auto_explore", "handler": self.dcss.auto_explore},
            {"name": "auto_fight", "handler": self.dcss.auto_fight},
            {"name": "rest", "handler": self.dcss.rest},
            {"name": "wait_turn", "handler": self.dcss.wait_turn},
            {"name": "go_upstairs", "handler": self.dcss.go_upstairs},
            {"name": "go_downstairs", "handler": self.dcss.go_downstairs},
            
            # Items
            {"name": "pickup", "handler": self.dcss.pickup},
            {"name": "wield", "handler": self.dcss.wield},
            {"name": "wear", "handler": self.dcss.wear},
            {"name": "quaff", "handler": self.dcss.quaff},
            {"name": "read_scroll", "handler": self.dcss.read_scroll},
            
            # Combat & abilities
            {"name": "use_ability", "handler": self.dcss.use_ability},
            {"name": "cast_spell", "handler": self.dcss.cast_spell},
            {"name": "attack", "handler": self.dcss.attack},
            {"name": "pray", "handler": self.dcss.pray},
            
            # Interface
            {"name": "confirm", "handler": self.dcss.confirm},
            {"name": "deny", "handler": self.dcss.deny},
            {"name": "escape", "handler": self.dcss.escape},
            {"name": "send_keys", "handler": self.dcss.send_keys},
            
            # Overlay & stats
            {"name": "update_overlay", "handler": self.dcss.update_overlay},
            {"name": "new_attempt", "handler": self.dcss.new_attempt},
            {"name": "record_death", "handler": self.dcss.record_death},
            {"name": "record_win", "handler": self.dcss.record_win},
        ]
        
        return tools
    
    async def run_game_session(self, session):
        """Run one complete game session until death or win."""
        try:
            # Initialize new game
            self.dcss.new_attempt()
            
            # Start the game (MiBe by default)
            initial_state = self.dcss.start_game(species_key='b', background_key='f', weapon_key='b')
            
            # TODO: Send initial message to Copilot session when SDK is available
            """
            response = await session.send_and_wait({
                "prompt": "Start playing DCSS. Call new_attempt() first, then begin your exploration. "
                         "Remember to call update_overlay() with brief thoughts after each action. "
                         f"Initial game state:\n{initial_state}"
            })
            """
            
            self.logger.info("Game started, waiting for AI to play...")
            
            # For now, just simulate waiting until game over
            # TODO: Replace with actual session interaction
            turn = 0
            while self.running and not self.dcss.is_dead:
                await asyncio.sleep(1)  # Placeholder - let the AI act through session
                turn += 1
                
                # Check game state periodically
                if turn % 60 == 0:  # Every minute
                    self.logger.info(f"Game still running... Turn {self.dcss.turn}, HP: {self.dcss.hp}/{self.dcss.max_hp}")
                
                # Timeout protection - no real game should last more than 10 hours
                if turn > 36000:  # 10 hours at 1 second per turn
                    self.logger.warning("Game timeout reached, ending session")
                    break
            
            # Game ended
            if self.dcss.is_dead:
                self.logger.info("Game ended - character died")
                # The AI should have already called record_death() but ensure it's recorded
                if hasattr(self, '_death_recorded') and not self._death_recorded:
                    self.dcss.record_death("timeout or unrecorded death")
            else:
                self.logger.info("Game ended - other reason")
            
        except Exception as e:
            self.logger.error(f"Error during game session: {e}")
            raise
        finally:
            # Ensure session cleanup
            if session:
                # TODO: Implement proper session cleanup when SDK is available
                pass
    
    async def run_forever(self):
        """Main loop - runs games forever until interrupted."""
        self.logger.info("Starting DCSS AI Driver")
        
        # TODO: Initialize Copilot client when SDK is available
        """
        self.client = CopilotClient()
        await self.client.start()
        """
        
        # Connect to DCSS server
        if not await self.connect_to_dcss():
            self.logger.error("Failed to connect to DCSS, exiting")
            return 1
        
        game_count = 0
        
        while self.running:
            try:
                game_count += 1
                self.logger.info(f"Starting game #{game_count}")
                
                # Load fresh system prompt + learnings
                system_prompt = self.load_system_prompt()
                
                # Create new Copilot session for this game
                session = await self.create_copilot_session(system_prompt)
                
                if session:
                    # Run the game
                    await self.run_game_session(session)
                else:
                    # Fallback for when Copilot SDK is not available
                    self.logger.warning("Running in simulation mode without Copilot SDK")
                    await asyncio.sleep(10)  # Simulate game time
                
                # Brief pause between games
                if self.running:
                    await asyncio.sleep(2)
                    
            except Exception as e:
                self.logger.error(f"Error in game loop: {e}")
                if self.running:
                    self.logger.info("Retrying in 30 seconds...")
                    await asyncio.sleep(30)
            
            # WebSocket connection recovery
            if self.running and not self.dcss._connected:
                self.logger.warning("DCSS connection lost, attempting to reconnect...")
                await self.connect_to_dcss()
        
        self.logger.info("Shutting down driver")
        return 0


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="DCSS AI Driver using GitHub Copilot SDK")
    parser.add_argument("--server-url", default="ws://localhost:8080/socket",
                       help="DCSS webtiles server WebSocket URL")
    parser.add_argument("--username", default="kurobot",
                       help="DCSS server username")
    parser.add_argument("--password", default="kurobot123",
                       help="DCSS server password")
    parser.add_argument("--model", default="claude-sonnet-4",
                       help="Copilot model to use")
    
    args = parser.parse_args()
    
    driver = DCSSDriver(args)
    try:
        return await driver.run_forever()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 0
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))