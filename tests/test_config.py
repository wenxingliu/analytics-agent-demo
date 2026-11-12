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


def test_guardrail_settings(monkeypatch):
    from analytics_agent.config import load_guardrails

    for key in ["GUARDRAIL_MIN_DATE", "GUARDRAIL_NO_INDIVIDUAL_DATA", "GUARDRAIL_NO_PII"]:
        monkeypatch.delenv(key, raising=False)
    assert load_guardrails().active() == ["no individual-level data", "no PII"]  # safe defaults
    monkeypatch.setenv("GUARDRAIL_MIN_DATE", "2026-01-01")
    monkeypatch.setenv("GUARDRAIL_NO_PII", "off")
    monkeypatch.setenv("GUARDRAIL_NO_INDIVIDUAL_DATA", "false")
    assert load_guardrails().active() == ["data from 2026-01-01 only"]
    monkeypatch.setenv("GUARDRAIL_MIN_DATE", "last year")
    with pytest.raises(ConfigError, match="YYYY-MM-DD"):
        load_guardrails()
    monkeypatch.setenv("GUARDRAIL_MIN_DATE", "")
    monkeypatch.setenv("GUARDRAIL_NO_PII", "maybe")
    with pytest.raises(ConfigError, match="true or false"):
        load_guardrails()
