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
- **`learnings.md`** — permanent knowledge base. Append-only. Every death becomes a lesson that improves future runs.

## Setup

### 1. DCSS Server (Docker)

```bash
cd server
docker compose up -d
```

This starts a DCSS webtiles server on `localhost:8080`.

### 2. Python Environment

```bash
cd ~/code/dcss-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. OpenClaw Skill

Register the skill in your OpenClaw workspace so the agent loads `SKILL.md` when playing:

```
skills/dcss-ai/SKILL.md → ~/code/dcss-ai/skill/SKILL.md
```

## Playing

The AI connects via a long-running Python REPL:

```bash
source .venv/bin/activate
python3 -i -c "
from dcss_ai.game import DCSSGame, Direction
dcss = DCSSGame()
dcss.connect('ws://localhost:8080/socket', 'kurobot', 'kurobot123')
print('Connected. Game IDs:', dcss._game_ids)
"
```

Then plays by writing Python:

```python
# Start a Minotaur Berserker
dcss.start_game(species_key='b', background_key='f', weapon_key='b')

# Explore
dcss.auto_explore()

# Check state
print(dcss.get_state_text())

# Fight
dcss.auto_fight()

# Heal up
if dcss.hp < dcss.max_hp:
    dcss.rest()
```

If the REPL dies, just reconnect — the DCSS server saves the game automatically.

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
│   ├── sandbox.py       # Restricted Python execution (unused in skill mode)
│   ├── server.py        # MCP server (unused, kept for future use)
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
