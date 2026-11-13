"""Chat client for OpenAI-compatible providers (Kimi, OpenAI)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache

from openai import OpenAI, OpenAIError

from analytics_agent.config import Provider


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Usage:
    """Token counts per model, summed over every call made while it was being tracked."""

    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, usage) -> None:
        if usage is None:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) or getattr(usage, "cached_tokens", 0) or 0
        counts = self.by_model.setdefault(
            model, {"calls": 0, "input": 0, "cached_input": 0, "output": 0}
        )
        counts["calls"] += 1
        counts["input"] += prompt - cached  # uncached input
        counts["cached_input"] += cached
        counts["output"] += getattr(usage, "completion_tokens", 0) or 0


_usage: ContextVar[Usage | None] = ContextVar("usage", default=None)


@contextmanager
def track_usage() -> Iterator[Usage]:
    """Record the token usage of every call made in this thread/context until the block ends."""
    usage = Usage()
    token = _usage.set(usage)
    try:
        yield usage
    finally:
        _usage.reset(token)


def _record(provider: Provider, response) -> None:
    if (usage := _usage.get()) is not None:
        usage.add(provider.model, getattr(response, "usage", None))


@cache
def _client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=3, timeout=60)


def chat(messages: list[dict], tools: list[dict], provider: Provider) -> ToolCall | str:
    """Call the provider (default temperature: some models reject overrides) and return its first tool call, or its text if it did not call a tool."""
    response = _client(provider.api_key, provider.base_url).chat.completions.create(
        model=provider.model, messages=messages, tools=tools
    )
    _record(provider, response)
    message = response.choices[0].message
    if not message.tool_calls:
        return message.content or ""
    call = message.tool_calls[0]
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return ToolCall(id=call.id, name=call.function.name, args=args)


def chat_json(messages: list[dict], name: str, schema: dict, provider: Provider) -> dict:
    """Call the provider without tools and return its reply parsed against a JSON schema ({} if unparseable).

    Use this instead of a single forced tool call: some reasoning models reject tools on this endpoint.
    """
    response = _client(provider.api_key, provider.base_url).chat.completions.create(
        model=provider.model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": name, "schema": schema, "strict": True},
        },
    )
    _record(provider, response)
    try:
        return json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}


NON_CHAT_MARKERS = (
    "embedding",
    "tts",
    "whisper",
    "dall-e",
    "moderation",
    "image",
    "audio",
    "realtime",
    "transcribe",
)


def list_models(provider: Provider) -> list[str]:
    """Model ids the provider offers for chat, or [] if the list can't be fetched."""
    try:
        ids = [m.id for m in _client(provider.api_key, provider.base_url).models.list()]
    except OpenAIError:
        return []
    return sorted(i for i in ids if not any(marker in i.lower() for marker in NON_CHAT_MARKERS))
