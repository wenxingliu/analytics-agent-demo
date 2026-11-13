from types import SimpleNamespace

from openai import OpenAIError

from analytics_agent import llm
from analytics_agent.config import Provider

PROVIDER = Provider("test", "Test", "key", "http://localhost", "model")


class FakeClient:
    def __init__(self, ids=None):
        def list_():
            if ids is None:
                raise OpenAIError("down")
            return [SimpleNamespace(id=i) for i in ids]

        self.models = SimpleNamespace(list=list_)


def test_list_models_sorted_and_chat_only(monkeypatch):
    monkeypatch.setattr(
        llm, "_client", lambda *_: FakeClient(["b-chat", "text-embedding-x", "a-chat"])
    )
    assert llm.list_models(PROVIDER) == ["a-chat", "b-chat"]


def test_list_models_failure_gives_empty_list(monkeypatch):
    monkeypatch.setattr(llm, "_client", lambda *_: FakeClient(None))
    assert llm.list_models(PROVIDER) == []


def test_track_usage_records_calls_inside_the_block_only():
    from types import SimpleNamespace

    from analytics_agent.llm import Usage, _record, track_usage

    provider = SimpleNamespace(model="m")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=7,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        )
    )
    _record(provider, response)  # not tracked: no error, nothing recorded
    with track_usage() as usage:
        _record(provider, response)
        _record(provider, response)
    _record(provider, response)
    assert isinstance(usage, Usage)
    assert usage.by_model == {"m": {"calls": 2, "input": 120, "cached_input": 80, "output": 14}}
