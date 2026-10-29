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
