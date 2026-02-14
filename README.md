# dcss-ai

An autonomous AI that plays [Dungeon Crawl Stone Soup](https://crawl.develz.org/) (DCSS), streams on Twitch, and learns from every death.

Built with the [GitHub Copilot SDK](https://github.com/github/copilot-sdk) — the AI calls game tools directly (move, fight, explore, use items) through a WebSocket connection to the DCSS webtiles server. Each game is one Copilot session; learnings persist across sessions in `learnings.md`.

## Architecture

```
driver.py
  │
  │  System prompt: system_prompt.md + learnings.md
  │  One Copilot SDK session per game
  │
  ├─ Copilot SDK ─── tool calls ───→ DCSSGame (game.py)
  │   │                                  │
  │   │  get_state_text()                │
  │   │  auto_explore()                  ├─→ dcss-api ──WebSocket──→ DCSS Server (Docker)
  │   │  attack("n")                     │
  │   │  update_overlay("hunting orc")   ├─→ ~/code/dcss-stream/stats.json
  │   │  record_death("orc priest")      │
  │   │  ...                             │
  │   │                                  │
  │   └─ On death/win: write learnings, end session
  │   └─ Loop: new session with fresh context
  │
  └─ Stream overlay polls stats.json every 2s
```

**Key design choices:**
- **One session = one game.** Fresh context each run, but `learnings.md` carries wisdom between games.
- **Tools, not code.** The AI calls discrete game actions — no REPL, no code generation.
- **Stream-aware.** The AI calls `update_overlay()` with a brief thought after every action, so Twitch viewers see its reasoning.

## Setup

### 1. Docker (for the DCSS server)

```bash
# Linux
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER && newgrp docker

# Windows — install Docker Desktop, enable WSL2 integration
```

### 2. Clone & install

```bash
cd ~/code
git clone https://github.com/nkhoit/dcss-ai.git
cd dcss-ai

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install github-copilot-sdk
```

### 3. Start the DCSS server

```bash
cd server && docker compose up -d
# Verify: docker ps (should show dcss-webtiles on port 8080)
# Web UI: http://localhost:8080
```

### 4. Authenticate Copilot CLI

The SDK requires the [Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) installed and authenticated:

```bash
copilot --version  # verify it's installed
```

### 5. Run the driver

```bash
source .venv/bin/activate
python dcss_ai/driver.py \
  --server-url ws://localhost:8080/socket \
  --username kurobot \
  --password kurobot123 \
  --model claude-sonnet-4
```

The driver connects to DCSS, creates a Copilot session, and plays forever — dying, learning, and restarting.

## Stream Setup

The stream overlay lives in `~/code/dcss-stream/`:

- **`overlay.html`** — Browser Source for OBS (transparent overlay with stats + thought bubble)
- **`stats.json`** — Polled by the overlay every 2s, updated by the game driver
- **`start-stream.sh`** — Launcher script (starts Docker, overlay server, driver, OBS)

Stats JSON format:
```json
{"attempt": 5, "wins": 0, "deaths": 4, "character": "MiBe", "xl": 7, "place": "D:5", "turn": 1234, "thought": "orc pack ahead, luring to corridor", "status": "playing"}
```

## Manual Play (OpenClaw Skill)

For interactive play through an [OpenClaw](https://github.com/openclaw/openclaw) agent, symlink the skill:

```bash
ln -s ~/code/dcss-ai/skill ~/.openclaw/workspace-main/skills/dcss-ai
```

Then tell your agent to "play DCSS" — it loads `SKILL.md` and plays through a Python REPL.

## Game API

### State queries (free, no turn cost)
```python
dcss.get_state_text()      # Full state dump
dcss.get_map(radius=7)     # ASCII map centered on @
dcss.get_inventory()       # [{slot, name, quantity}, ...]
dcss.get_nearby_enemies()  # Sorted by distance
dcss.get_stats()           # One-line: HP/MP/AC/EV/XL/place/turn
dcss.get_messages(n=10)    # Recent game messages
```

### Actions (consume turns)
```python
dcss.move("n")             # n/s/e/w/ne/nw/se/sw
dcss.auto_explore()        # Explore until interrupted
dcss.auto_fight()          # Fight nearest (blocked at low HP)
dcss.attack("n")           # Melee in direction (works at any HP)
dcss.rest()                # Rest until healed
dcss.pickup()              # Pick up items
dcss.go_downstairs()       # Descend
dcss.wield("a")            # Equip weapon by slot
dcss.wear("b")             # Wear armour
dcss.quaff("a")            # Drink potion
dcss.read_scroll("a")      # Read scroll
dcss.use_ability("a")      # God/species ability (a=Berserk)
dcss.cast_spell("a", "n")  # Cast spell + direction
dcss.send_keys("abc")      # Raw keystrokes (escape hatch)
```

### Overlay & lifecycle
```python
dcss.update_overlay("thought")  # Update stream overlay
dcss.new_attempt()              # Increment attempt counter
dcss.record_death("cause")     # Record death + increment counter
dcss.record_win()              # Record win
```

## Project Structure

```
dcss-ai/
├── dcss_ai/
│   ├── driver.py        # Autonomous game driver (Copilot SDK)
│   ├── game.py          # DCSSGame — high-level API over dcss-api
│   ├── system_prompt.md # System prompt for the playing agent
│   ├── sandbox.py       # Restricted Python execution (for REPL mode)
│   ├── server.py        # MCP server (experimental)
│   └── main.py          # Entry point (REPL mode)
├── skill/
│   ├── SKILL.md         # OpenClaw skill: strategy guide + API reference
│   └── learnings.md     # Persistent knowledge from past deaths
├── server/
│   └── docker-compose.yml
└── requirements.txt
```

## Credits

- [DCSS](https://github.com/crawl/crawl) — the game
- [dcss-api](https://github.com/EricFecteau/dcss-api) by EricFecteau — WebSocket API layer
- [GitHub Copilot SDK](https://github.com/github/copilot-sdk) — LLM agent framework
- [OpenClaw](https://github.com/openclaw/openclaw) — mission control & monitoring
- [frozenfoxx/crawl](https://hub.docker.com/r/frozenfoxx/crawl) — Docker image
