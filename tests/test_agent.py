import pandas as pd
import pytest
from openai import OpenAIError

from analytics_agent import agent, db, guardrails, llm
from analytics_agent.agent import Conversation
from analytics_agent.config import Provider
from analytics_agent.metadata import Knowledge, Metadata, Table

PROVIDER = Provider("test", "Test", "key", "http://localhost", "model")


@pytest.fixture
def metadata() -> Metadata:
    table = Table(
        table="table_a",
        description="neutral",
        columns=[{"name": "col_x", "type": "INTEGER"}],
    )
    return Metadata(tables=[table], knowledge=Knowledge(), examples=[])


@pytest.fixture
def script(monkeypatch):
    """Make llm.chat return scripted replies, and db return canned results."""
    replies: list = []
    seen_prompts: list = []

    def fake_chat(messages, tools, provider):
        seen_prompts.append(messages)
        return replies.pop(0)

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(db, "dialect", lambda: "sqlite")
    monkeypatch.setattr(db, "validate_sql", lambda sql: sql)
    monkeypatch.setattr(guardrails, "enforce", lambda sql, *args: sql)

    def fake_run(sql):
        if "bad" in sql:
            raise db.QueryError("no such column")
        return pd.DataFrame({"col_x": [1, 2]})

    monkeypatch.setattr(db, "run_query", fake_run)
    return replies


def call(name: str, **args) -> llm.ToolCall:
    return llm.ToolCall(id=f"id-{name}", name=name, args=args)


def test_clarification(metadata, script):
    script.append(call("ask_clarification", question="Which one?", options=["a", "b"]))
    reply = agent.answer(metadata, Conversation(), "ambiguous", PROVIDER)
    assert reply.question == "Which one?" and reply.options == ["a", "b"]


def test_sql_error_then_retry_succeeds(metadata, script):
    script += [
        call("run_sql", sql="SELECT bad"),
        call("run_sql", sql="SELECT col_x"),
        call("final_answer", answer="Done"),
    ]
    conversation = Conversation()
    reply = agent.answer(metadata, conversation, "question", PROVIDER)
    assert reply.text == "Done" and reply.sql == "SELECT col_x" and len(reply.dataframe) == 2
    tool_outputs = [m["content"] for m in conversation.messages if m["role"] == "tool"]
    assert tool_outputs[0].startswith("Error: no such column")


def test_plain_text_is_the_final_answer(metadata, script):
    script.append("Just text")
    assert agent.answer(metadata, Conversation(), "hi", PROVIDER).text == "Just text"


def test_max_steps_cutoff(metadata, script):
    script += [call("run_sql", sql="SELECT bad")] * 5
    reply = agent.answer(metadata, Conversation(), "question", PROVIDER)
    assert "rephras" in reply.text and reply.error == "no such column" and reply.sql == "SELECT bad"


def test_old_tool_results_are_shortened(metadata, script):
    conversation = Conversation()
    script += [
        call("run_sql", sql="SELECT col_x"),
        call("final_answer", answer="One"),
        call("final_answer", answer="Two"),
    ]
    agent.answer(metadata, conversation, "first", PROVIDER)
    agent.answer(metadata, conversation, "second", PROVIDER)
    tool = next(m for m in conversation.recent_messages() if m["role"] == "tool")
    assert "\n" not in tool["content"] and "Rows: 2" in tool["content"]


def test_api_error_is_shown_and_not_kept_in_model_history(metadata, monkeypatch):
    def failing_chat(messages, tools, provider):
        raise OpenAIError("boom")

    monkeypatch.setattr(llm, "chat", failing_chat)
    monkeypatch.setattr(db, "dialect", lambda: "sqlite")
    conversation = Conversation()
    reply = agent.answer(metadata, conversation, "question", PROVIDER)
    assert "boom" in reply.error
    assert conversation.messages == []
    assert [role for role, _ in conversation.turns] == ["user", "assistant"]
