#!/usr/bin/env python3
"""Abstract base classes for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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
        """Send a message to the LLM and get a response.
        
        Args:
            message: The message to send
            timeout: Maximum time to wait for a response
            
        Returns:
            SessionResult with completion status, response text, and usage stats
        """
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
        """Create a new session with the given configuration.
        
        Args:
            system_prompt: The system prompt to use
            tools: List of tool definitions (provider-agnostic format)
            model: Model name/identifier to use
            
        Returns:
            A new session instance
        """
        pass