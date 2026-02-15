#!/usr/bin/env python3
"""OpenAI-compatible provider (works with OpenAI, Ollama, Groq, etc.)."""

import asyncio
import json
import sys
import time
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from .base import LLMProvider, LLMSession, SessionResult, write_monologue, clear_monologue


# Max conversation rounds to keep (sliding window). DCSS state is always
# queryable via get_state_text(), so old context is disposable.
MAX_HISTORY_ROUNDS = 50


def _tool_def_to_openai(tool_def: Dict[str, Any]) -> Dict[str, Any]:
    """Convert provider-agnostic tool dict to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool_def["name"],
            "description": tool_def["description"],
            "parameters": tool_def["parameters"],
        },
    }


class OpenAISession(LLMSession):
    """OpenAI-compatible chat session with tool calling."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str,
        openai_tools: List[Dict[str, Any]],
        handlers: Dict[str, Any],
    ):
        self.client = client
        self.model = model
        self.handlers = handlers
        self.openai_tools = openai_tools
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self.usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "total_duration_ms": 0,
        }
        # Clear monologue for new session
        clear_monologue()

    def _trim_history(self):
        """Keep system message + last MAX_HISTORY_ROUNDS pairs."""
        # Count non-system messages
        non_system = self.messages[1:]
        if len(non_system) > MAX_HISTORY_ROUNDS * 2:
            keep = MAX_HISTORY_ROUNDS * 2
            self.messages = [self.messages[0]] + non_system[-keep:]

    async def send(self, message: str, timeout: float = 120) -> SessionResult:
        """Send message, run tool loop until assistant responds with text or stops."""
        self.messages.append({"role": "user", "content": message})
        self._trim_history()

        start = time.time()
        try:
            result_text = await asyncio.wait_for(
                self._tool_loop(), timeout=timeout
            )
            return SessionResult(
                completed=True, text=result_text, usage=self.usage_totals.copy()
            )
        except asyncio.TimeoutError:
            return SessionResult(
                completed=False, text="", usage=self.usage_totals.copy()
            )

    async def _tool_loop(self) -> str:
        """Call the model in a loop, executing tool calls until done."""
        while True:
            t0 = time.time()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=self.openai_tools or None,
                tool_choice="auto" if self.openai_tools else None,
            )
            elapsed_ms = int((time.time() - t0) * 1000)

            choice = response.choices[0]
            msg = choice.message

            # Track usage
            if response.usage:
                self.usage_totals["input_tokens"] += response.usage.prompt_tokens or 0
                self.usage_totals["output_tokens"] += response.usage.completion_tokens or 0
            self.usage_totals["api_calls"] += 1
            self.usage_totals["total_duration_ms"] += elapsed_ms

            # If the model wants to call tools
            if msg.tool_calls:
                # Append assistant message with tool calls
                self.messages.append(msg.model_dump())

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}

                    handler = self.handlers.get(fn_name)
                    if handler:
                        try:
                            result = handler(args)
                        except Exception as e:
                            result = f"Error: {e}"
                    else:
                        result = f"Unknown tool: {fn_name}"

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })

                continue  # Loop back for next model call

            # No tool calls — assistant text response
            text = msg.content or ""
            if text.strip():
                sys.stdout.write(text + "\n")
                sys.stdout.flush()
                write_monologue(text)

            self.messages.append({"role": "assistant", "content": text})
            return text


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider. Set base_url for Ollama/Groq/etc."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key or "ollama"  # Ollama doesn't need a real key
        self.client: Optional[AsyncOpenAI] = None

    async def start(self) -> None:
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def stop(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None

    async def create_session(
        self, system_prompt: str, tools: List[Dict[str, Any]], model: str
    ) -> LLMSession:
        if not self.client:
            raise RuntimeError("Provider not started")

        openai_tools = [_tool_def_to_openai(t) for t in tools]
        handlers = {t["name"]: t["handler"] for t in tools}

        return OpenAISession(
            client=self.client,
            model=model,
            system_prompt=system_prompt,
            openai_tools=openai_tools,
            handlers=handlers,
        )
