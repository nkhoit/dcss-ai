#!/usr/bin/env python3
"""Mock LLM provider for CI testing. Executes a scripted sequence of tool calls."""

from typing import Any, Dict, List, Optional

from .base import LLMProvider, LLMSession, SessionResult


class MockSession(LLMSession):
    """A session that executes a pre-scripted sequence of tool calls."""

    def __init__(self, script: List[Dict[str, Any]], handlers: Dict[str, Any]):
        self.script = list(script)  # copy
        self.handlers = handlers
        self.results: List[Dict[str, Any]] = []  # log of calls + results
        self.usage_totals = {
            "input_tokens": 0, "output_tokens": 0, "api_calls": 0,
            "total_duration_ms": 0,
        }

    async def send(self, message: str, timeout: float = 120) -> SessionResult:
        """Execute the next batch of scripted tool calls until a 'stop' marker."""
        if not self.script:
            return SessionResult(completed=True, text="Script exhausted.", usage=self.usage_totals)

        # Execute tool calls until we hit a stop point or run out
        while self.script:
            step = self.script.pop(0)

            if step.get("stop"):
                # Return control to driver (simulates LLM responding with text)
                self.usage_totals["api_calls"] += 1
                return SessionResult(
                    completed=len(self.script) == 0,
                    text=step.get("text", ""),
                    usage=self.usage_totals.copy(),
                )

            name = step["name"]
            args = step.get("args", {})
            handler = self.handlers.get(name)

            if not handler:
                raise RuntimeError(f"Mock script calls unknown tool: {name}")

            result = handler(args)
            self.results.append({"name": name, "args": args, "result": result})

        # Script fully consumed
        self.usage_totals["api_calls"] += 1
        return SessionResult(completed=True, text="Done.", usage=self.usage_totals)


class MockProvider(LLMProvider):
    """Mock provider that plays a scripted game.
    
    Usage:
        provider = MockProvider(script=[
            {"name": "new_attempt", "args": {}},
            {"name": "start_game", "args": {"species_key": "b", "background_key": "f", "weapon_key": "b"}},
            {"name": "get_state_text", "args": {}},
            {"stop": True},  # return to driver, driver sends continue prompt
            {"name": "auto_explore", "args": {}},
            {"name": "get_map", "args": {"radius": 5}},
            {"name": "quit_game", "args": {}},
            {"stop": True, "text": "GAME_OVER"},  # final stop
        ])
    """

    def __init__(self, script: Optional[List[Dict[str, Any]]] = None):
        self.script = script or []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def create_session(
        self, system_prompt: str, tools: List[Dict[str, Any]], model: str
    ) -> MockSession:
        handlers = {t["name"]: t["handler"] for t in tools}
        return MockSession(self.script, handlers)
