#!/usr/bin/env python3
"""Abstract base classes for LLM providers."""

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


from dcss_ai.overlay import send_thought, send_reset


# Monologue file path — legacy fallback
MONOLOGUE_PATH = os.environ.get(
    "DCSS_MONOLOGUE_PATH",
    str(Path(__file__).parent.parent.parent / "monologue.jsonl"),
)


def write_monologue(text: str, path: str = MONOLOGUE_PATH) -> None:
    """Push a thought to connected overlays and append to file as fallback."""
    text = text.strip()
    if not text:
        return
    send_thought(text)
    entry = {"ts": time.time(), "text": text}
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def clear_monologue(path: str = MONOLOGUE_PATH) -> None:
    """Signal overlays to reset and clear the monologue file."""
    send_reset()
    with open(path, "w") as f:
        pass


@dataclass
class SessionResult:
    """Result from an LLM session interaction."""
    completed: bool
    text: str
    usage: Dict[str, Any]


class LLMSession(ABC):
    """Abstract base class for LLM sessions."""
    
    @abstractmethod
    async def send(self, message: str, timeout: float = 120) -> SessionResult:
        """Send a message to the LLM and get a response."""
        pass


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def start(self) -> None:
        """Initialize the provider connection."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Clean up the provider connection."""
        pass
    
    @abstractmethod
    async def create_session(self, system_prompt: str, tools: List[Dict[str, Any]], model: str) -> LLMSession:
        """Create a new session with the given configuration."""
        pass