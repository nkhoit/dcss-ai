#!/usr/bin/env python3
"""Provider factory module."""

from typing import Optional
from .base import LLMProvider


def get_provider(name: str, base_url: Optional[str] = None, api_key: Optional[str] = None) -> LLMProvider:
    """Get a provider instance by name.
    
    Args:
        name: Provider name ("copilot")
        
    Returns:
        Provider instance
    """
    if name == "copilot":
        from .copilot import CopilotProvider
        return CopilotProvider()
    elif name == "mock":
        from .mock import MockProvider
        return MockProvider()
    else:
        raise ValueError(f"Unknown provider '{name}'. Available: copilot, mock")


def list_providers() -> list[str]:
    """Get list of available provider names."""
    return ["copilot"]
