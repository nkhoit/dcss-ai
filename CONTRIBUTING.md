# Contributing to dcss-ai

Thanks for your interest! This project is an autonomous AI agent that plays Dungeon Crawl Stone Soup via the webtiles WebSocket API, driven by LLM tool-calling.

## Getting Started

### Prerequisites
- Python 3.12+
- Docker (for the DCSS server)
- An LLM provider (GitHub Copilot CLI, OpenAI API key, or compatible)

### Setup
```bash
git clone https://github.com/nkhoit/dcss-ai.git
cd dcss-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the DCSS Server
```bash
docker run -d --name dcss-webtiles -p 8080:8080 ghcr.io/nkhoit/dcss-webtiles:latest
```

### Running the AI
```bash
# Edit config.json for your setup (model, credentials, etc.)
python -m dcss_ai.driver
```

See `config.json` for all configurable options. CLI args override config file values.

## Development Workflow

1. **Read `AGENTS.md`** — architecture, conventions, gotchas
2. **Run tests before and after changes:**
   ```bash
   docker run -d --name dcss-webtiles -p 8080:8080 ghcr.io/nkhoit/dcss-webtiles:latest
   python -m pytest tests/ -v
   ```
3. **Keep game logic in `game.py`** — tools, providers, and driver shouldn't contain DCSS knowledge
4. **Add tests for new tools** — at minimum a mock provider test covering the happy path
5. **Update `system_prompt.md`** if you add/change/remove tools — the LLM reads this

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Tests must pass in CI (GitHub Actions spins up a real DCSS server)
- Update `system_prompt.md` if tool signatures change
- Update `AGENTS.md` if architecture changes

## Project Structure

```
dcss_ai/           — Python package
  config.py        — Configuration defaults and loading
  driver.py        — Main loop and session management
  game.py          — Game state, actions, all tool implementations
  webtiles.py      — WebSocket client for DCSS webtiles
  tools.py         — Provider-agnostic tool definitions
  providers/       — LLM provider implementations
config.json        — Per-deployment configuration
system_prompt.md   — LLM system prompt (gameplay instructions)
learnings.md       — AI-written lessons (persists across games)
tests/             — Integration and mock provider tests
```

## Adding Tools

See `AGENTS.md` for the full guide. Short version:

1. Method on `DCSSGame` in `game.py`
2. Tool dict in `build_tools()` in `tools.py`
3. Docs in `system_prompt.md`
4. Test in `tests/test_mock_provider.py`

## Adding Providers

Subclass `LLMProvider` + `LLMSession` from `providers/base.py`. See `providers/mock.py` for a minimal example, `providers/copilot.py` for a full implementation.

## Code Style

- Python 3.12+, f-strings, type hints on public APIs
- No formatter/linter enforced yet — just keep it readable
- `logging` for infrastructure, `sys.stdout.write` for game narration output

## License

[Check repository for license information]
