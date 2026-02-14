"""MCP server for DCSS AI."""
import os
import asyncio
from typing import Any, Dict
from mcp.server import Server
from mcp.types import Tool, TextContent

from .game import DCSSGame
from .sandbox import Sandbox


class DCSSMCPServer:
    """MCP server exposing DCSS game controls."""
    
    def __init__(self):
        self.server = Server("dcss-ai")
        self.game = DCSSGame()
        self.sandbox = Sandbox(self.game)
        
        self.server_url = os.getenv("DCSS_SERVER_URL", "ws://localhost:8080/socket")
        self.username = os.getenv("DCSS_USERNAME", "kurobot")
        self.password = os.getenv("DCSS_PASSWORD", "kurobot123")
        
        self._setup_tools()
    
    def _setup_tools(self):
        @self.server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="dcss_start_game",
                    description=(
                        "Start a new DCSS game. Connect to server if needed, then start a game.\n"
                        "Species/background/weapon are single-char hotkeys from the character creation menu.\n"
                        "Common combos: Minotaur Berserker (species='b', background='f', weapon='b' for mace)"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "species": {"type": "string", "description": "Species hotkey (single char)"},
                            "background": {"type": "string", "description": "Background hotkey (single char)"},
                            "weapon": {"type": "string", "description": "Weapon hotkey (single char, optional)", "default": ""},
                        },
                        "required": ["species", "background"],
                    },
                ),
                Tool(
                    name="dcss_state",
                    description="Get current game state: stats, map, messages, inventory.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="dcss_execute",
                    description=(
                        "Execute Python code against the DCSS game API.\n"
                        "The 'dcss' object is available with methods like:\n"
                        "  dcss.move('n'), dcss.auto_explore(), dcss.auto_fight(),\n"
                        "  dcss.rest(), dcss.pickup(), dcss.quaff('a'), dcss.wield('b'),\n"
                        "  dcss.go_downstairs(), dcss.cast_spell('a', 'n')\n"
                        "Properties: dcss.hp, dcss.max_hp, dcss.mp, dcss.position, dcss.xl, etc.\n"
                        "Direction constants: Direction.N, Direction.S, etc.\n"
                        "Use print() to output information. Code runs in a sandbox with 10s timeout."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Python code to execute"},
                        },
                        "required": ["code"],
                    },
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]):
            try:
                if name == "dcss_start_game":
                    return await self._start_game(arguments)
                elif name == "dcss_state":
                    return await self._get_state()
                elif name == "dcss_execute":
                    return await self._execute(arguments)
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]
    
    async def _start_game(self, args: Dict[str, Any]) -> list[TextContent]:
        if not self.game._connected:
            self.game.connect(self.server_url, self.username, self.password)
        
        state = self.game.start_game(
            species_key=args["species"],
            background_key=args["background"],
            weapon_key=args.get("weapon", ""),
        )
        return [TextContent(type="text", text=state)]
    
    async def _get_state(self) -> list[TextContent]:
        if not self.game._in_game:
            return [TextContent(type="text", text="No active game. Use dcss_start_game first.")]
        return [TextContent(type="text", text=self.game.get_state_text())]
    
    async def _execute(self, args: Dict[str, Any]) -> list[TextContent]:
        code = args.get("code", "")
        if not code:
            return [TextContent(type="text", text="Error: code is required")]
        if not self.game._in_game:
            return [TextContent(type="text", text="No active game. Use dcss_start_game first.")]
        
        result = self.sandbox.execute(code)
        
        parts = []
        if result["output"]:
            parts.append(f"Output:\n{result['output']}")
        if result["error"]:
            parts.append(f"Error:\n{result['error']}")
        if result["messages"]:
            parts.append("Game Messages:\n" + "\n".join(f"  {m}" for m in result["messages"]))
        
        # Append current state summary
        if self.game._in_game:
            parts.append(f"\n{self.game.get_stats()}")
        if self.game.is_dead:
            parts.append("*** GAME OVER — YOU ARE DEAD ***")
        
        return [TextContent(type="text", text="\n\n".join(parts) if parts else "OK (no output)")]
    
    async def run(self):
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read, write):
            await self.server.run(read, write)


async def main():
    server = DCSSMCPServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())
