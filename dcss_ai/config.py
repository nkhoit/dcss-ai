"""Centralized configuration with defaults, file overrides, and CLI overrides.

Priority (highest wins): CLI args > config.json > defaults here
"""

import json
from pathlib import Path

DEFAULTS = {
    # DCSS server
    "server_url": "ws://localhost:8080/socket",
    "username": "dcssai",
    "password": "dcssai",

    # LLM provider
    "provider": "copilot",
    "model": "claude-sonnet-4.5",
    "base_url": None,
    "api_key": None,

    # Gameplay
    "single": False,
    "narrate_interval": 5,  # 0 = disable forced narration

    # Timeouts
    "silent_timeout": 60,   # seconds with no output = stuck
    "max_retries": 5,       # consecutive timeouts before abandoning game
    "turn_timeout": 120,    # per-turn timeout (seconds)

    # Debug
    "debug": False,         # enable DEBUG-level logging (tool calls, etc.)

    # Overlay
    "overlay_port": 8889,   # SSE server port for stream overlay

    # Post-death analyzer
    "analyzer_enabled": True,           # LLM-based death analysis
    "analyzer_model": "claude-sonnet-4.5",  # model for analysis
}

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def load_config(cli_args=None) -> dict:
    """Load config: defaults → config.json → CLI args."""
    config = dict(DEFAULTS)

    # Layer 2: config.json overrides
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                file_config = json.load(f)
            config.update({k: v for k, v in file_config.items() if v is not None})
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: failed to load {CONFIG_PATH}: {e}")

    # Layer 3: CLI args override (skip None values)
    if cli_args:
        cli_dict = vars(cli_args) if hasattr(cli_args, '__dict__') else cli_args
        config.update({k: v for k, v in cli_dict.items() if v is not None})

    return config
