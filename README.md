# dcss-ai

An autonomous AI agent that plays [Dungeon Crawl Stone Soup](https://crawl.develz.org/) (DCSS), learns from every death, and streams on Twitch.

Built with the [GitHub Copilot SDK](https://github.com/github/copilot-sdk). The AI calls game tools directly — move, fight, explore, use items — through a pure-Python WebSocket connection to a local DCSS webtiles server. Each game is one Copilot session; accumulated learnings persist across games in `learnings.md`.

## How It Works

```
driver.py — Game loop (infinite: play → die → learn → repeat)
  │
  ├─ Copilot SDK session (one per game)
  │   ├─ System prompt: system_prompt.md + learnings.md
  │   ├─ 35+ tools: get_state, move, auto_explore, attack, quaff, ...
  │   └─ On death/win: write_learning() → end session → next game
  │
  ├─ DCSSGame (game.py) — High-level game API
  │   └─ WebTilesConnection (webtiles.py) — Pure Python WebSocket client
  │       └─ DCSS Webtiles Server (Docker, port 8080)
  │
  └─ Stream overlay (stats.json → OBS browser source)
```

**Key design choices:**
- **One session = one game.** Fresh LLM context each run. `learnings.md` carries wisdom between games.
- **Tools, not code generation.** The AI calls discrete game actions — no REPL, no arbitrary code.
- **Pure Python WebSocket client.** No Rust dependencies. Handles zlib decompression, message batching, keepalive pings, More prompts, and all DCSS protocol quirks.
- **Stream-aware.** `update_overlay()` writes the AI's current thought to `stats.json`, polled by an OBS browser source overlay.

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (for the DCSS server)
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) (authenticated, with Copilot Pro+ or Enterprise)

### Setup

```bash
git clone https://github.com/nkhoit/dcss-ai.git
cd dcss-ai

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install github-copilot-sdk

# Start the DCSS server
cd server && docker compose up -d
# Verify: http://localhost:8080 should show the DCSS lobby
```

### Run

```bash
source .venv/bin/activate
python dcss_ai/driver.py \
  --server-url ws://localhost:8080/socket \
  --username kurobot \
  --password kurobot123 \
  --model claude-sonnet-4
```

The driver connects to DCSS, creates a Copilot session, and plays forever — dying, learning, and restarting. Use `--single` for a one-game test run.

## Testing

Requires Docker. No LLM or API keys needed — tests exercise the game API directly.

```bash
# Start server, run tests, stop server
./run.sh server-start
./run.sh test
./run.sh server-stop
```

Or manually:
```bash
pip install -r requirements.txt pytest
docker run -d --name dcss-webtiles -p 8080:8080 ghcr.io/nkhoit/dcss-webtiles:latest
python -m pytest tests/test_integration.py -v
docker stop dcss-webtiles && docker rm dcss-webtiles
```

## Game API

The `DCSSGame` class provides a clean Python API over the DCSS webtiles protocol.

### State (free, no turn cost)
| Method | Returns |
|---|---|
| `get_state_text()` | Full dump: stats, messages, enemies, inventory, map |
| `get_map(radius=7)` | ASCII map centered on `@` |
| `get_inventory()` | `[{slot, name, quantity}, ...]` |
| `get_nearby_enemies()` | `[{name, direction, distance, threat}, ...]` |
| `get_stats()` | One-line: `HP/MP/AC/EV/XL/place/turn` |
| `get_messages(n=10)` | Recent game messages |

### Actions (consume turns)
| Method | Description |
|---|---|
| `move(dir)` | Move one step (`n/s/e/w/ne/nw/se/sw`) |
| `auto_explore()` | Explore until interrupted |
| `auto_fight()` | Tab-fight nearest (blocked at low HP) |
| `attack(dir)` | Melee in direction (works at any HP) |
| `rest()` | Rest until healed |
| `pickup()` | Pick up items |
| `go_downstairs()` / `go_upstairs()` | Use stairs |
| `wield(slot)` / `wear(slot)` | Equip weapon/armour |
| `quaff(slot)` / `read_scroll(slot)` | Use consumables |
| `zap_wand(slot, dir)` | Zap a wand |
| `use_ability(key)` | God/species ability |
| `cast_spell(key, dir)` | Cast spell |
| `examine(slot)` | Inspect an item |

### Stream Overlay
| Method | Description |
|---|---|
| `update_overlay(thought)` | Update stats.json with current thought |
| `new_attempt()` | Increment attempt counter |
| `record_death(cause)` / `record_win()` | Track game outcomes |

## OpenClaw Skill

For interactive play through an [OpenClaw](https://github.com/openclaw/openclaw) agent:

```bash
ln -s ~/code/dcss-ai/skill ~/.openclaw/workspace-main/skills/dcss-ai
```

Then tell your agent to "play DCSS" — it loads `SKILL.md` and plays through a Python REPL.

## Project Structure

```
dcss-ai/
├── dcss_ai/
│   ├── driver.py          # Autonomous driver (Copilot SDK, game loop)
│   ├── game.py            # DCSSGame — high-level game API
│   ├── webtiles.py        # Pure Python WebSocket client for DCSS protocol
│   ├── system_prompt.md   # System prompt for the playing agent
│   ├── sandbox.py         # Restricted Python execution (REPL mode)
│   ├── server.py          # MCP server (experimental, for OpenClaw skill)
│   └── main.py            # Entry point (REPL mode)
├── skill/
│   ├── SKILL.md           # OpenClaw skill definition
│   ├── game_state.md      # Active game state (updated during play)
│   └── learnings.md       # Persistent knowledge from past games
├── server/
│   └── docker-compose.yml # DCSS webtiles server (nkhoit/dcss-webtiles)
├── tests/
│   └── test_integration.py # Integration tests (25 deterministic tests)
├── run.sh               # Helper script (server-start, server-stop, test)
└── requirements.txt
```

## Credits

- [DCSS](https://github.com/crawl/crawl) — Dungeon Crawl Stone Soup
- [GitHub Copilot SDK](https://github.com/github/copilot-sdk) — LLM agent framework
- [nkhoit/dcss-webtiles](https://github.com/nkhoit/dcss-webtiles) — Docker image
- [dcss-api](https://github.com/EricFecteau/dcss-api) — Reference for the webtiles protocol
