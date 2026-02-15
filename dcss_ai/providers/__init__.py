#!/usr/bin/env python3
"""Provider factory module."""

from typing import Dict, Type
from .base import LLMProvider
from .copilot import CopilotProvider


# Registry of available providers
PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "copilot": CopilotProvider,
}


def get_provider(name: str) -> LLMProvider:
    """Get a provider instance by name.
    
    Args:
        name: Provider name (e.g., "copilot")
        
    Returns:
        Provider instance
        
    Raises:
        ValueError: If provider name is not recognized
    """
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available providers: {available}")
    
    provider_class = PROVIDERS[name]
    return provider_class()


def list_providers() -> list[str]:
    """Get list of available provider names."""
    return list(PROVIDERS.keys())