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

The `DCSSGame` class in [`game.py`](dcss_ai/game.py) provides a clean Python API over the DCSS webtiles protocol — state queries (free, no turn cost) and actions (movement, combat, items, abilities).

## Credits

- [DCSS](https://github.com/crawl/crawl) — Dungeon Crawl Stone Soup
- [GitHub Copilot SDK](https://github.com/github/copilot-sdk) — LLM agent framework
- [nkhoit/dcss-webtiles](https://github.com/nkhoit/dcss-webtiles) — Docker image
- [dcss-api](https://github.com/EricFecteau/dcss-api) — Reference for the webtiles protocol
