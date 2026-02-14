# DCSS-AI MCP Server

An MCP (Model Context Protocol) server that allows LLMs to play Dungeon Crawl Stone Soup (DCSS) via tool calls, using the Glyphbox-style "execute_code" pattern.

## Overview

This project provides a bridge between Large Language Models and DCSS, allowing AI to play the game through a sandboxed Python environment. The AI gets access to a `dcss` object that wraps the low-level dcss-api WebSocket interface into a clean, high-level API.

## Components

- **`dcss_ai/game.py`** - DCSSGame class that wraps dcss-api WebtilePy
- **`dcss_ai/sandbox.py`** - Restricted Python execution environment
- **`dcss_ai/server.py`** - MCP server with three tools
- **`dcss_ai/main.py`** - CLI entry point

## MCP Tools

1. **`dcss_start_game(species, background, weapon)`** - Start a new game
2. **`dcss_state()`** - Get current game state (map, stats, messages, inventory) 
3. **`dcss_execute(code)`** - Execute Python code against the game API

## Installation

```bash
cd ~/code/dcss-ai
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Start the MCP Server

```bash
cd ~/code/dcss-ai
source .venv/bin/activate
python -m dcss_ai.main
```

### Environment Variables

- `DCSS_SERVER_URL` - WebSocket URL (default: ws://localhost:8080/socket)
- `DCSS_USERNAME` - DCSS username (default: kurobot)  
- `DCSS_PASSWORD` - DCSS password (default: kurobot123)

### Start DCSS Server

The project includes a Docker setup for running a DCSS webtiles server:

```bash
cd ~/code/dcss-ai/server
docker-compose up -d
```

This starts a DCSS server on localhost:8080.

## Example LLM Usage

Once connected to the MCP server, an LLM can:

1. Start a game:
```json
{"tool": "dcss_start_game", "species": "a", "background": "a"}
```

2. Get current state:
```json
{"tool": "dcss_state"}
```

3. Execute game actions:
```json
{"tool": "dcss_execute", "code": "dcss.move('n')"}
{"tool": "dcss_execute", "code": "dcss.auto_explore()"}
{"tool": "dcss_execute", "code": "print(dcss.get_stats())"}
```

## Game API Reference

The `dcss` object available in the sandbox provides:

### Properties
- `dcss.hp`, `dcss.max_hp`, `dcss.mp`, `dcss.max_mp`
- `dcss.ac`, `dcss.ev`, `dcss.sh` (armor class, evasion, shield)
- `dcss.str`, `dcss.int`, `dcss.dex`
- `dcss.xl`, `dcss.place`, `dcss.depth`, `dcss.god`, `dcss.gold`
- `dcss.position`, `dcss.is_dead`, `dcss.turn`

### Actions
- `dcss.move(direction)` - Move in direction ("n", "s", "e", "w", "ne", etc.)
- `dcss.auto_explore()` - Start auto-exploration
- `dcss.auto_fight()` - Auto-fight nearest enemy
- `dcss.rest()` - Rest until healed
- `dcss.pickup()` - Pick up items
- `dcss.use_ability(key)`, `dcss.cast_spell(key)`
- `dcss.quaff(key)`, `dcss.read(key)`, `dcss.wield(key)`
- And many more...

### Queries  
- `dcss.get_messages(n=10)` - Recent game messages
- `dcss.get_inventory()` - Current inventory
- `dcss.get_map()` - ASCII map around player
- `dcss.get_stats()` - Formatted stats string

## Security

The sandbox restricts Python execution to prevent harmful operations:
- No imports, file I/O, or system access
- 10 second execution timeout
- Limited to basic builtins and the `dcss` game object
- AST validation before execution

## Development

Test that everything compiles:

```bash
cd ~/code/dcss-ai
source .venv/bin/activate
python3 -c "from dcss_ai.game import DCSSGame; from dcss_ai.sandbox import Sandbox; print('OK')"
```

## Architecture

This follows the Glyphbox pattern where the LLM writes Python code against a game API object rather than making direct API calls. This provides more flexibility and allows for complex multi-step actions within a single code execution.

The dcss-api package handles the low-level WebSocket communication with DCSS webtiles, while this project provides the high-level MCP interface suitable for LLM interaction.