# AGENTS.md — Coding Guide for dcss-ai

## Architecture

```
dcss_ai/
  config.py       — Centralized defaults, config.json loader, CLI merge
  driver.py       — Main loop: session management, retry logic, shutdown
  game.py         — DCSSGame: all game state, tools impl, overlay, notepad
  webtiles.py     — WebSocket client: connect, send keys, recv messages
  tools.py        — Tool definitions (provider-agnostic dicts), build_tools()
  providers/
    base.py       — Abstract LLMProvider / LLMSession interfaces
    copilot.py    — GitHub Copilot SDK provider
    openai.py     — OpenAI-compatible provider
    mock.py       — Scripted provider for tests
```

### Data Flow

```
LLM Provider → tool call → tools.py handler → game.py method → webtiles.py → DCSS server
                                                    ↓
                                              state update (HP, map, inventory, etc.)
                                                    ↓
                                              tool result string → back to LLM
```

### Key Boundaries

- **`game.py`** owns all game state and logic. Tools call methods here.
- **`webtiles.py`** is a dumb WebSocket transport — no game logic.
- **`tools.py`** is glue — maps tool names to `game.py` methods. Provider-agnostic.
- **`providers/`** handle LLM communication. They don't know about DCSS.
- **`driver.py`** orchestrates: create session → send prompt → handle retries → cleanup.
- **`config.py`** is the single source of truth for defaults and configuration.

## Config System

Priority: CLI args > `config.json` > `config.py` DEFAULTS

All tunable values (model, credentials, timeouts, narrate interval) live in `config.py` DEFAULTS.
Per-deployment overrides go in `config.json`. One-off overrides via CLI args.

## Adding a New Tool

1. Add the method to `DCSSGame` in `game.py`
2. Add the tool definition dict in `build_tools()` in `tools.py`:
   ```python
   {"name": "tool_name", "description": "...", "parameters": {...}, "handler": handler}
   ```
3. Add to `system_prompt.md` so the LLM knows about it
4. Add a mock test in `tests/test_mock_provider.py`
5. If it involves UI state (menus/popups), respect `_current_menu`/`_current_popup`/`_pending_prompt` blocking

## Adding a New Provider

1. Subclass `LLMProvider` and `LLMSession` from `providers/base.py`
2. Implement `start()`, `stop()`, `create_session()` on the provider
3. Implement `send(prompt) → SendResult` on the session
4. Register in `providers/__init__.py` `get_provider()`
5. Tool handlers come pre-built from `build_tools()` — just call them by name

## Game State Rules

- **`_act()`** is the central dispatcher for all game actions. It handles:
  - Menu/popup blocking (returns error if UI is open)
  - Pending prompt blocking (stat increase, etc.)
  - Narrate enforcement (configurable interval)
  - Input mode handling (mode 0=travelling, 1=ready, 5=more, 7=text prompt)
  - Death detection (only via `close` message, never mode 7)
- **Never bypass `_act()`** — all game actions must go through it
- **`_session_ended`** flag prevents actions after death/win is recorded
- **`_in_game`** tracks whether a game is active

## Testing

### Run Tests
```bash
# Requires a running DCSS server
docker run -d --name dcss-webtiles -p 8080:8080 ghcr.io/nkhoit/dcss-webtiles:latest
python -m pytest tests/ -v
```

### Test Categories
- **`test_integration.py`** — Direct `game.py` API tests against live DCSS server
- **`test_mock_provider.py`** — Full pipeline tests (driver → tools → game) with scripted LLM
- **`test_ui_manual.py`** — Manual verification scripts (not run in CI)

### Writing Tests
- Use `random_username()` for test isolation (no shared state between tests)
- Never assert on randomness-dependent outcomes (map layout, enemy spawns)
- Assert on invariants: turn advances, HP is positive, state types are correct
- Mock provider tests should cover the full tool call → result cycle

## CI/CD

GitHub Actions runs on push/PR to `main`:
1. Spins up DCSS webtiles Docker container
2. Installs Python deps
3. Runs `pytest tests/ -v`
4. Tears down container

### Docker Image
`ghcr.io/nkhoit/dcss-webtiles` — auto-built weekly via GitHub Actions.
Separate repo: [nkhoit/dcss-webtiles](https://github.com/nkhoit/dcss-webtiles)

## Style

- No linter enforced (yet), but keep it clean
- Type hints on public methods
- Docstrings on classes and non-obvious methods
- f-strings over `.format()`
- `logging` module for driver/provider logs, `sys.stdout.write` for game narration

## Common Gotchas

- **DCSS 0.34 quit confirmation** is `"quit"` not `"yes"` — type each letter individually
- **Stat prompts are mandatory** — can't be escaped, must answer with uppercase S/I/D
- **Mode 7 ≠ death** — it's a text input prompt. Death is only signaled by `close` message
- **Mode 0 = travelling** — don't escape it, wait for auto-explore to finish
- **Pickup with `,`** not `g` — `g` opens a selection menu that hangs on 0.34
- **Tool `__name__` matters** — Copilot SDK uses it for registration. Set before `@define_tool`
- **WebSocket keepalive** is application-level JSON `{"msg": "ping"}`, not WS frames
