#!/usr/bin/env python3
"""Copilot SDK provider implementation."""

import asyncio
import sys
import time
from typing import Any, Dict, List, Optional

from copilot import CopilotClient
from copilot.tools import define_tool
from copilot.generated.session_events import SessionEventType
from pydantic import BaseModel, Field

from .base import LLMProvider, LLMSession, SessionResult, write_monologue, clear_monologue


def _create_pydantic_model(tool_def: Dict[str, Any]) -> type:
    """Create a Pydantic model class from a tool parameter schema."""
    
    # Get the parameters schema
    params_schema = tool_def["parameters"]
    properties = params_schema.get("properties", {})
    required = params_schema.get("required", [])
    
    # Build field definitions
    fields = {}
    for name, prop in properties.items():
        field_type = str  # Default to string
        if prop.get("type") == "integer":
            field_type = int
        elif prop.get("type") == "boolean":
            field_type = bool
            
        default_val = prop.get("default", ...)
        if name not in required and default_val == ...:
            default_val = None
            
        description = prop.get("description", "")
        
        if default_val == ... or default_val is None:
            if name in required:
                fields[name] = (field_type, Field(description=description))
            else:
                fields[name] = (Optional[field_type], Field(default=None, description=description))
        else:
            fields[name] = (field_type, Field(default=default_val, description=description))
    
    # If no fields, use empty model
    if not fields:
        fields = {}
    
    # Create the model class dynamically
    model_name = f"{tool_def['name'].title()}Params"
    return type(model_name, (BaseModel,), {"__annotations__": {k: v[0] for k, v in fields.items()}, 
                                          **{k: v[1] for k, v in fields.items()}})


def _make_copilot_tool(name: str, description: str, handler, param_model):
    """Create a Copilot tool function with properly captured closure variables."""
    # We need the function name set BEFORE @define_tool captures it
    def make_inner():
        def tool_fn(params: param_model) -> str:
            params_dict = params.dict() if hasattr(params, 'dict') else params.__dict__
            return handler(params_dict)
        tool_fn.__name__ = name
        tool_fn.__qualname__ = name
        return define_tool(description=description)(tool_fn)
    return make_inner()


class CopilotSession(LLMSession):
    """Copilot SDK session wrapper."""
    
    def __init__(self, copilot_session, tool_handlers: Dict[str, Any]):
        self.session = copilot_session
        self.tool_handlers = tool_handlers
        self.usage_totals = {
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "premium_requests": 0, "api_calls": 0,
            "total_duration_ms": 0
        }
        self._current_message = []  # accumulate deltas
        
        # Clear monologue for new session
        clear_monologue()
        
        # Activity tracking
        self.last_delta_time = time.time()
        self.last_tool_time = time.time()
        
        # Set up event handling
        self.session.on(self._handle_event)
    
    def _handle_event(self, event):
        """Handle Copilot session events."""
        if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            content = event.data.delta_content
            if content:
                self._current_message.append(content)
                self.last_delta_time = time.time()
                # Still stream to stdout for logs
                if content.strip():
                    sys.stdout.write(content)
                    sys.stdout.flush()
        elif event.type == SessionEventType.ASSISTANT_MESSAGE:
            # Complete message — write to monologue
            full_text = "".join(self._current_message)
            self._current_message = []
            write_monologue(full_text)
            sys.stdout.write("\n")
            sys.stdout.flush()
        elif event.type == SessionEventType.ASSISTANT_USAGE:
            d = event.data
            self.usage_totals["input_tokens"] += int(d.input_tokens or 0)
            self.usage_totals["output_tokens"] += int(d.output_tokens or 0)
            self.usage_totals["cache_read_tokens"] += int(d.cache_read_tokens or 0)
            self.usage_totals["cache_write_tokens"] += int(d.cache_write_tokens or 0)
            self.usage_totals["premium_requests"] += int(d.cost or 0)
            self.usage_totals["api_calls"] += 1
            self.usage_totals["total_duration_ms"] += int(d.duration or 0)
        elif event.type == SessionEventType.TOOL_EXECUTION_START:
            self.last_tool_time = time.time()
    
    async def send(self, message: str, timeout: float = 120) -> SessionResult:
        """Send message and wait for completion.
        
        Uses adaptive timeout: resets when activity (deltas/tools) is detected.
        Only fires when the model goes completely silent.
        """
        try:
            task = asyncio.ensure_future(
                self.session.send_and_wait({"prompt": message}, timeout=7200)
            )
            
            # Poll until task completes or model goes silent
            silent_limit = 60  # seconds of no output = stuck
            while not task.done():
                await asyncio.sleep(1)
                since_delta = time.time() - self.last_delta_time
                since_tool = time.time() - self.last_tool_time
                last_activity = min(since_delta, since_tool)
                
                if last_activity > silent_limit:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    return SessionResult(
                        completed=False,
                        text="",
                        usage=self.usage_totals.copy()
                    )
            
            return SessionResult(
                completed=True,
                text="",
                usage=self.usage_totals.copy()
            )
        except asyncio.TimeoutError:
            return SessionResult(
                completed=False,
                text="",
                usage=self.usage_totals.copy()
            )


class CopilotProvider(LLMProvider):
    """Copilot SDK provider."""
    
    def __init__(self):
        self.client: Optional[CopilotClient] = None
    
    async def start(self) -> None:
        """Initialize Copilot client."""
        self.client = CopilotClient()
        await self.client.start()
    
    async def stop(self) -> None:
        """Stop Copilot client."""
        if self.client:
            await self.client.stop()
            self.client = None
    
    async def create_session(self, system_prompt: str, tools: List[Dict[str, Any]], model: str) -> LLMSession:
        """Create a new Copilot session."""
        if not self.client:
            raise RuntimeError("Provider not started")
        
        # Convert provider-agnostic tools to Copilot format
        copilot_tools = []
        tool_handlers = {}
        
        for tool_def in tools:
            name = tool_def["name"]
            description = tool_def["description"]
            handler = tool_def["handler"]
            
            # Create Pydantic model for parameters
            param_model = _create_pydantic_model(tool_def)
            
            # Create Copilot tool function via factory to avoid closure bug
            tool_func = _make_copilot_tool(name, description, handler, param_model)
            
            # Store the function with the correct name
            tool_func.__name__ = name
            copilot_tools.append(tool_func)
            tool_handlers[name] = handler
        
        # Create Copilot session
        session = await self.client.create_session({
            "model": model,
            "system_message": system_prompt,
            "tools": copilot_tools,
            "streaming": True,
            "available_tools": [],  # disable built-in tools
            "infinite_sessions": {
                "enabled": True,  # let the SDK handle context management
            },
        })
        
        return CopilotSession(session, tool_handlers)