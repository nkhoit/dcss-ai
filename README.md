# dcss-ai

An autonomous AI agent that plays [Dungeon Crawl Stone Soup](https://crawl.develz.org/) (DCSS), learns from every death, and streams on Twitch.

The AI calls game tools directly — move, fight, explore, use items — through a pure-Python WebSocket connection to a local DCSS webtiles server. Each game is one LLM session; accumulated learnings persist across games in `learnings.md`.

Supports multiple LLM providers: GitHub Copilot SDK, OpenAI, Ollama, Groq, or any OpenAI-compatible API.

## How It Works

```
driver.py — Game loop (infinite: play → die → learn → repeat)
  │
  ├─ LLM session (one per game, provider-agnostic)
  │   ├─ System prompt: system_prompt.md + learnings.md
  │   ├─ 39 tools: get_state, move, auto_explore, attack, quaff, ...
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
- **Provider-agnostic.** Swap LLM backends without changing game logic or tool definitions.

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (for the DCSS server)

### Setup

```bash
git clone https://github.com/nkhoit/dcss-ai.git
cd dcss-ai

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the DCSS server
cd server && docker compose up -d
# Verify: http://localhost:8080 should show the DCSS lobby
```

### Run with Ollama

No API key needed — just a running [Ollama](https://ollama.com) instance:

```bash
python -m dcss_ai.driver \
  --provider openai \
  --base-url http://localhost:11434/v1 \
  --model gemma3:12b-it-qat \
  --username kurobot --password kurobot123 \
  --single
```

### Run with OpenAI

```bash
export OPENAI_API_KEY=sk-...
python -m dcss_ai.driver \
  --provider openai \
  --base-url https://api.openai.com/v1 \
  --model gpt-4o \
  --username kurobot --password kurobot123 \
  --single
```

### Run with GitHub Copilot SDK

Requires [Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) (authenticated, Copilot Pro+ or Enterprise):

```bash
pip install github-copilot-sdk
python -m dcss_ai.driver \
  --provider copilot \
  --model claude-sonnet-4 \
  --username kurobot --password kurobot123
```

### CLI Reference

```
--provider    LLM provider: copilot, openai (default: copilot)
--base-url    Base URL for OpenAI-compatible providers
--api-key     API key (optional for Ollama, reads OPENAI_API_KEY if unset)
--model       Model name (default: claude-sonnet-4)
--server-url  DCSS webtiles WebSocket URL (default: ws://localhost:8080/socket)
--username    DCSS account username (default: kurobot)
--password    DCSS account password (default: kurobot123)
--single      Play one game then exit
```

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
- [nkhoit/dcss-webtiles](https://github.com/nkhoit/dcss-webtiles) — Docker image
- [dcss-api](https://github.com/EricFecteau/dcss-api) — Reference for the webtiles protocol
