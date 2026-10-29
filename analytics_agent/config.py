"""Settings read from the environment (and .env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible chat endpoint."""

    name: str
    label: str
    api_key: str
    base_url: str
    model: str  # default model; the UI can override it


@dataclass(frozen=True)
class Settings:
    semantic_layer_path: Path
    database_url: str
    max_rows: int
    query_timeout_seconds: int
    max_agent_steps: int


def load_settings() -> Settings:
    get = os.environ.get
    return Settings(
        semantic_layer_path=Path(get("SEMANTIC_LAYER_PATH", "./semantic_layer")),
        database_url=get("DATABASE_URL", "sqlite:///data/demo.db"),
        max_rows=int(get("MAX_ROWS", "1000")),
        query_timeout_seconds=int(get("QUERY_TIMEOUT_SECONDS", "30")),
        max_agent_steps=int(get("MAX_AGENT_STEPS", "5")),
    )


def load_providers() -> dict[str, Provider]:
    """Providers with an API key set, in order; LLM_PROVIDER picks the first one."""
    get = os.environ.get
    candidates = [
        Provider(
            "kimi",
            "Kimi (Moonshot)",
            get("MOONSHOT_API_KEY", ""),
            get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
            get("KIMI_MODEL", ""),
        ),
        Provider(
            "openai",
            "OpenAI",
            get("OPENAI_API_KEY", ""),
            get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            get("OPENAI_MODEL", ""),
        ),
    ]
    available = [p for p in candidates if p.api_key]
    if not available:
        raise ConfigError(
            "No LLM provider configured. Set MOONSHOT_API_KEY and/or OPENAI_API_KEY. "
            "See .env.example."
        )
    preferred = get("LLM_PROVIDER", "")
    available.sort(key=lambda p: p.name != preferred)  # stable: preferred first
    return {p.name: p for p in available}


settings = load_settings()
