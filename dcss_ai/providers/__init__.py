#!/usr/bin/env python3
"""Provider factory module."""

from typing import Dict, Optional, Type
from .base import LLMProvider


def get_provider(name: str, base_url: Optional[str] = None, api_key: Optional[str] = None) -> LLMProvider:
    """Get a provider instance by name.
    
    Args:
        name: Provider name ("copilot" or "openai")
        base_url: Base URL for OpenAI-compatible providers (e.g. Ollama)
        api_key: API key (optional for Ollama)
        
    Returns:
        Provider instance
    """
    if name == "copilot":
        from .copilot import CopilotProvider
        return CopilotProvider()
    elif name == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(base_url=base_url, api_key=api_key)
    elif name == "mock":
        from .mock import MockProvider
        return MockProvider()
    else:
        raise ValueError(f"Unknown provider '{name}'. Available: copilot, openai, mock")


def list_providers() -> list[str]:
    """Get list of available provider names."""
    return ["copilot", "openai"]