"""Chat client for OpenAI-compatible providers (Kimi, OpenAI)."""

import json
from dataclasses import dataclass
from functools import cache

from openai import OpenAI, OpenAIError

from analytics_agent.config import Provider


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@cache
def _client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=3, timeout=60)


def chat(messages: list[dict], tools: list[dict], provider: Provider) -> ToolCall | str:
    """Call the provider (default temperature: some models reject overrides) and return its first tool call, or its text if it did not call a tool."""
    response = _client(provider.api_key, provider.base_url).chat.completions.create(
        model=provider.model, messages=messages, tools=tools
    )
    message = response.choices[0].message
    if not message.tool_calls:
        return message.content or ""
    call = message.tool_calls[0]
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return ToolCall(id=call.id, name=call.function.name, args=args)


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
