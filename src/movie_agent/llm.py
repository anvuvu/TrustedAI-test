"""Thin OpenAI chat-completions client with function calling (design §7.1).

The key comes from `OPENAI_API_KEY` (loaded from `.env` by the CLI); the model from config.
Tests use a scripted client with the same `complete` interface.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from movie_agent.config import AgentConfig


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str | None = None


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0

    def as_message(self) -> dict[str, Any]:
        """The assistant message to append to the conversation."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.raw_arguments},
                }
                for c in self.tool_calls
            ]
        return message


class LLMClient(Protocol):
    model: str

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class OpenAIClient:
    """Chat completions with `tool_choice="required"`, so every step is a tool call and the
    turn always ends through the `final_answer` tool."""

    def __init__(self, cfg: AgentConfig) -> None:
        if cfg.model == "<set-me>":
            raise RuntimeError("agent.model is '<set-me>' in configs/default.yaml; ask the author")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set (copy .env.example to .env)")
        from openai import OpenAI

        self.cfg = cfg
        self.model = cfg.model
        self._client = OpenAI(api_key=key, timeout=cfg.request_timeout_s)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="required",
            temperature=self.cfg.temperature,
        )
        latency = (time.perf_counter() - start) * 1000
        message = response.choices[0].message
        calls = [
            _parse_call(c.id, c.function.name, c.function.arguments)
            for c in message.tool_calls or []
        ]
        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(message.content, calls, _flat_usage(usage), round(latency, 1))


def _parse_call(call_id: str, name: str, raw: str) -> ToolCall:
    try:
        args = json.loads(raw or "{}")
        return ToolCall(call_id, name, args if isinstance(args, dict) else {}, raw)
    except json.JSONDecodeError as exc:
        return ToolCall(call_id, name, {}, raw, parse_error=str(exc))


def _flat_usage(usage: dict[str, Any]) -> dict[str, int]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {k: int(usage[k]) for k in keys if isinstance(usage.get(k), int)}
