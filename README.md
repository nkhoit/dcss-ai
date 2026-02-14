# dcss-ai

An AI agent that plays [Dungeon Crawl Stone Soup](https://crawl.develz.org/) (DCSS) through the webtiles WebSocket API. Built as an [OpenClaw](https://github.com/openclaw/openclaw) skill — the AI plays via a persistent Python REPL, writing code against a high-level game API.

Inspired by [Glyphbox](https://github.com/kenforthewin/glyphbox)'s approach to LLM roguelike play: instead of one action per LLM call, the AI writes Python code that can loop, branch, and batch actions — dramatically reducing token usage across a 2000+ turn game.

## How It Works

```
OpenClaw Session
  │
  │  reads skill/SKILL.md (strategy + API reference)
  │  reads skill/game_state.md (active game context)
  │  reads skill/learnings.md (knowledge from past deaths)
  │
  ├─ exec: long-running Python REPL (holds WebSocket connection)
  │   │
  │   │  dcss.auto_explore()
  │   │  dcss.auto_fight()
  │   │  dcss.get_map()
  │   │  ...
  │   │
  │   └─→ dcss-api (PyPI) ──WebSocket──→ DCSS Webtiles Server (Docker)
  │
  └─ writes: game_state.md (every 5-10 turns)
             learnings.md (after every death)
```

The AI's memory survives context compaction through two files:
- **`game_state.md`** — current game lifeboat (character, floor, objective, threats). Overwritten regularly.
- **`learnings.md`** — permanent knowledge base. Append-only with periodic synthesis. Every death becomes a lesson that improves future runs.

## Setup (from scratch)

### 1. Install Docker

You need Docker to run the DCSS webtiles game server.

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Log out and back in, or use: newgrp docker
```

**Windows (WSL2):**
- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows
- In Docker Desktop: Settings → General → check "Use WSL 2 based engine"
- In Docker Desktop: Settings → Resources → WSL Integration → enable your distro
- Docker commands will then work inside your WSL shell

**Verify Docker works:**
```bash
docker ps
```

If you get a permission error, you may need `sg docker -c "docker ps"` or log out/in for the group change to take effect. If `sg docker -c "..."` is needed, use it for all Docker commands below.

### 2. Install Python Dependencies

You need Python 3.10+ with venv support.

```bash
# Install venv support (Ubuntu/Debian — often missing by default)
sudo apt install -y python3-venv

# If your system uses python3.12 specifically:
sudo apt install -y python3.12-venv
```

### 3. Clone and Set Up the Project

```bash
# Clone
cd ~/code  # or wherever you keep projects
git clone https://github.com/nkhoit/dcss-ai.git
cd dcss-ai

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Start the DCSS Server

```bash
cd ~/code/dcss-ai/server
docker compose up -d

# Verify it's running
docker ps  # should show dcss-webtiles on port 8080

# You can also open http://localhost:8080 in a browser to see the webtiles UI
```

The server saves game data in a Docker volume (`dcss-data`), so saves persist across restarts.

```bash
# Stop the server (saves are preserved)
docker compose down

# Destroy everything including saves (fresh start)
docker compose down -v
```

### 5. Register as OpenClaw Skill

Symlink the skill directory into your OpenClaw workspace so the agent discovers it:

```bash
ln -s ~/code/dcss-ai/skill ~/.openclaw/workspace-main/skills/dcss-ai
```

After this, OpenClaw will show `dcss-ai` in its available skills and load `SKILL.md` when asked to play DCSS.

### 6. Verify Everything Works

```bash
cd ~/code/dcss-ai
source .venv/bin/activate
python3 -c "
from dcss_ai.game import DCSSGame, Direction
dcss = DCSSGame()
dcss.connect('ws://localhost:8080/socket', 'testbot', 'testbot123')
print('Connected! Game IDs:', dcss._game_ids)
state = dcss.start_game(species_key='b', background_key='f', weapon_key='b')
print(state[:300])
dcss.quit_game()
dcss.disconnect()
print('All good!')
"
```

If this prints game state and "All good!", you're ready to play.

## Architecture Overview

This project supports two different approaches to DCSS AI gameplay:

### 1. OpenClaw Skill (Manual Control)
The traditional approach where an OpenClaw agent manually controls the game through a Python REPL:

```
OpenClaw Session
  │
  │  reads skill/SKILL.md (strategy + API reference)
  │  reads skill/game_state.md (active game context)
  │  reads skill/learnings.md (knowledge from past deaths)
  │
  ├─ exec: long-running Python REPL (holds WebSocket connection)
  │   │
  │   │  dcss.auto_explore()
  │   │  dcss.auto_fight()
  │   │  dcss.get_map()
  │   │  ...
  │   │
  │   └─→ dcss-api (PyPI) ──WebSocket──→ DCSS Webtiles Server (Docker)
  │
  └─ writes: game_state.md (every 5-10 turns)
             learnings.md (after every death)
```

### 2. Autonomous Driver (GitHub Copilot SDK)
The new autonomous approach using `driver.py` and GitHub Copilot SDK:

```
driver.py (Python)
  │
  │  One Copilot session = one game
  │  System prompt = system_prompt.md + learnings.md
  │
  ├─ GitHub Copilot SDK Session
  │   │  Tools: all DCSSGame methods registered
  │   │  Agent plays autonomously until death/win
  │   │  Updates stream overlay: ~/code/dcss-stream/stats.json
  │   │
  │   └─→ dcss-api ──WebSocket──→ DCSS Webtiles Server (Docker)
  │
  ├─ On Death/Win: end session, write learnings
  ├─ Create new session with fresh context
  └─ Loop forever
```

**Key differences:**
- **Game driver**: Uses Copilot SDK to drive gameplay autonomously
- **One session per game**: Fresh context each game, but learnings persist
- **Stream integration**: Updates `~/code/dcss-stream/stats.json` for overlay
- **Mission control**: OpenClaw instance monitors but doesn't play

## Playing

### Option 1: Autonomous Driver (Recommended)

For continuous autonomous gameplay using GitHub Copilot SDK:

```bash
cd ~/code/dcss-ai
source .venv/bin/activate
python dcss_ai/driver.py --server-url ws://localhost:8080/socket --username kurobot --password kurobot123
```

The driver will:
1. Connect to DCSS server
2. Create Copilot sessions with fresh context each game
3. Register all DCSS game methods as tools
4. Let the AI play until death/win
5. Update learnings and loop forever

**Stream Integration**: If you have `~/code/dcss-stream/` set up, the driver will update `stats.json` for the stream overlay.

### Option 2: Manual OpenClaw Skill

Tell your OpenClaw agent to "play DCSS" — it will load the skill and start a game session. Or manually:

### Start the REPL

```bash
cd ~/code/dcss-ai && source .venv/bin/activate && python3 -i -c "
from dcss_ai.game import DCSSGame, Direction
dcss = DCSSGame()
dcss.connect('ws://localhost:8080/socket', 'kurobot', 'kurobot123')
print('Connected. Game IDs:', dcss._game_ids)
"
```

### Start a Game

```python
# Minotaur Berserker — recommended starting combo
dcss.start_game(species_key='b', background_key='f', weapon_key='b')
```

### Play

```python
dcss.auto_explore()           # Explore the floor
dcss.auto_fight()             # Fight nearest enemy
dcss.rest()                   # Rest until healed
print(dcss.get_state_text())  # See everything
print(dcss.get_map())         # See the map
dcss.go_downstairs()          # Descend
```

### Reconnect After Interruption

The DCSS server saves your game automatically. If the REPL dies, just start a new one and connect — your game loads from the save.

## Game API

### Properties (free, no turn cost)
```python
dcss.hp, dcss.max_hp, dcss.mp, dcss.max_mp
dcss.ac, dcss.ev, dcss.sh
dcss.strength, dcss.intelligence, dcss.dexterity
dcss.xl, dcss.place, dcss.depth, dcss.god, dcss.gold
dcss.position, dcss.turn, dcss.is_dead
```

### State Queries (free)
```python
dcss.get_messages(n=10)    # Recent game messages
dcss.get_inventory()       # [{slot, name, quantity}, ...]
dcss.get_map(radius=7)     # ASCII map centered on @
dcss.get_stats()           # One-line stats summary
dcss.get_state_text()      # Full state dump
```

### Actions (consume turns)
```python
dcss.move("n")             # n/s/e/w/ne/nw/se/sw
dcss.auto_explore()        # Explore until interrupted
dcss.auto_fight()          # Fight nearest enemy
dcss.rest()                # Rest until healed
dcss.pickup()              # Pick up items
dcss.go_downstairs()       # Descend
dcss.wield("a")            # Equip weapon by slot
dcss.wear("b")             # Wear armour by slot
dcss.quaff("a")            # Drink potion
dcss.read_scroll("a")      # Read scroll
dcss.cast_spell("a", "n")  # Cast spell + direction
dcss.use_ability("a")      # God/species ability
dcss.send_keys("abc")      # Raw keystrokes (escape hatch)
```

## Project Structure

```
dcss-ai/
├── dcss_ai/
│   ├── game.py          # DCSSGame — high-level API over dcss-api
│   ├── sandbox.py       # Restricted Python execution environment
│   ├── server.py        # MCP server (for future use)
│   └── main.py          # Entry point
├── skill/
│   ├── SKILL.md         # Strategy guide + API reference for the AI
│   ├── game_state.md    # Active game context (survives compaction)
│   └── learnings.md     # Permanent knowledge from past deaths
├── server/
│   └── docker-compose.yml
└── requirements.txt
```

## Dependencies

- [dcss-api](https://github.com/EricFecteau/dcss-api) — Rust/Python WebSocket wrapper for DCSS webtiles
- [OpenClaw](https://github.com/openclaw/openclaw) — AI agent framework
- Docker — for running the DCSS webtiles server

## Credits

- [DCSS](https://github.com/crawl/crawl) — the game itself
- [dcss-api](https://github.com/EricFecteau/dcss-api) by EricFecteau — WebSocket API layer
- [Glyphbox](https://github.com/kenforthewin/glyphbox) by kenforthewin — inspiration for the execute-code pattern
- [frozenfoxx/crawl](https://hub.docker.com/r/frozenfoxx/crawl) — Docker image
