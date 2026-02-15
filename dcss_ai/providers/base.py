#!/usr/bin/env python3
"""Abstract base classes for LLM providers."""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


from dcss_ai.overlay import send_thought, send_reset


def write_monologue(text: str) -> None:
    """Push a thought to connected overlays via SSE."""
    text = text.strip()
    if not text:
        return
    send_thought(text)


def clear_monologue() -> None:
    """Signal overlays to reset their feed."""
    send_reset()


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