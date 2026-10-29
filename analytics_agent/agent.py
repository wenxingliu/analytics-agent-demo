"""The agent loop: prompt → Kimi tool call → clarify, run SQL, or answer."""

import json
from dataclasses import dataclass, field

import pandas as pd
from openai import OpenAIError

from analytics_agent import db, llm
from analytics_agent.config import Provider, settings
from analytics_agent.metadata import Metadata
from analytics_agent.prompts import build_system_prompt

RECENT_TURNS = 10
PREVIEW_ROWS = 20

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Ask the user one question before writing SQL, when the request is ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Run a read-only SQL query and get back a preview of the results.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "Reply to the user, after seeing results or when no SQL is needed.",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    },
]


@dataclass
class Reply:
    text: str = ""
    question: str = ""
    options: list[str] = field(default_factory=list)
    sql: str = ""
    dataframe: pd.DataFrame | None = None
    error: str = ""


@dataclass
class Conversation:
    """OpenAI-format messages for the model, plus the turns the UI displays."""

    messages: list[dict] = field(default_factory=list)
    turns: list[tuple[str, str | Reply]] = field(default_factory=list)

    def recent_messages(self) -> list[dict]:
        """Last RECENT_TURNS turns; tool results from older turns are cut to a one-line summary."""
        user_starts = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        start = user_starts[-RECENT_TURNS] if len(user_starts) > RECENT_TURNS else 0
        current_turn = user_starts[-1] if user_starts else 0
        recent = []
        for i, m in enumerate(self.messages[start:], start):
            if m["role"] == "tool" and i < current_turn:
                m = {**m, "content": m["content"].split("\n", 1)[0]}
            recent.append(m)
        return recent


def preview(df: pd.DataFrame) -> str:
    """Summary line plus the first rows, as the model sees query results."""
    summary = f"Columns: {', '.join(map(str, df.columns))} | Rows: {len(df)}"
    return f"{summary}\n{df.head(PREVIEW_ROWS).to_csv(index=False)}"


def answer(
    metadata: Metadata, conversation: Conversation, user_message: str, provider: Provider
) -> Reply:
    """Handle one user message and return what to show."""
    messages_before = len(conversation.messages)
    conversation.messages.append({"role": "user", "content": user_message})
    conversation.turns.append(("user", user_message))
    try:
        reply = _run_loop(metadata, conversation, user_message, provider)
    except OpenAIError as e:
        # Drop the unanswered exchange from the model's history, but keep it on screen
        del conversation.messages[messages_before:]
        reply = Reply(error=f"The model service failed: {e}")
    conversation.turns.append(("assistant", reply))
    return reply


def _run_loop(
    metadata: Metadata, conversation: Conversation, user_message: str, provider: Provider
) -> Reply:
    history = conversation.recent_messages()
    history_text = " ".join(str(m.get("content") or "") for m in history if m["role"] == "user")
    system = {
        "role": "system",
        "content": build_system_prompt(metadata, db.dialect(), user_message, history_text),
    }
    last_sql, last_error, last_result = "", "", None

    for _ in range(settings.max_agent_steps):
        result = llm.chat([system, *conversation.recent_messages()], TOOLS, provider)

        if isinstance(result, str) or result.name == "final_answer":
            text = result if isinstance(result, str) else str(result.args.get("answer", ""))
            conversation.messages.append({"role": "assistant", "content": text})
            return Reply(text=text, sql=last_sql, dataframe=last_result)

        if result.name == "ask_clarification":
            question = str(result.args.get("question", ""))
            conversation.messages.append({"role": "assistant", "content": question})
            return Reply(question=question, options=list(result.args.get("options") or []))

        if result.name == "run_sql":
            sql = str(result.args.get("sql", ""))
            try:
                last_sql = db.validate_sql(sql)
                last_result = db.run_query(last_sql)
                last_error, output = "", preview(last_result)
            except (db.UnsafeSQLError, db.QueryError) as e:
                last_sql, last_error = sql, str(e)
                last_result, output = None, f"Error: {e}"
            _add_tool_exchange(conversation, result, last_sql, output)
        else:
            _add_tool_exchange(conversation, result, "", f"Error: unknown tool {result.name}")

    conversation.messages.append({"role": "assistant", "content": "I could not answer that."})
    return Reply(
        text="Sorry, I couldn't answer that. Try rephrasing.",
        sql=last_sql,
        dataframe=last_result,
        error=last_error,
    )


def _add_tool_exchange(
    conversation: Conversation, call: llm.ToolCall, sql: str, output: str
) -> None:
    """Record the tool call and its result so later steps and turns can see them."""
    arguments = json.dumps({"sql": sql} if call.name == "run_sql" else call.args)
    conversation.messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": arguments}}],
    })  # fmt: skip
    conversation.messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
