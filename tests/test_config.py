import pytest

from analytics_agent.config import ConfigError, load_providers

KEYS = ["MOONSHOT_API_KEY", "KIMI_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "LLM_PROVIDER"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_no_provider_is_an_error():
    with pytest.raises(ConfigError, match="No LLM provider"):
        load_providers()


def test_only_providers_with_a_key_are_listed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    assert list(load_providers()) == ["openai"]


def test_llm_provider_picks_the_default(monkeypatch):
    for key in KEYS[:4]:
        monkeypatch.setenv(key, "x")
    assert list(load_providers()) == ["kimi", "openai"]
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert list(load_providers()) == ["openai", "kimi"]
