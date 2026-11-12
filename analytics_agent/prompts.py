"""Turns the semantic layer into the system prompt."""

from datetime import date

from analytics_agent.config import settings
from analytics_agent.metadata import (
    Example,
    Knowledge,
    Metadata,
    Table,
    pick_tables,
    words,
)

MAX_EXAMPLES = 5

SYSTEM_TEMPLATE = """\
You are Analytics Agent, an expert data analyst who writes {dialect} SQL.
You answer questions about this business: {business_overview}

## Rules
- Use only tables and columns listed in the Data Catalog. Never invent columns.
- Follow the business rules and metric definitions in Knowledge exactly.
- Write a single read-only SELECT query (CTEs are allowed).
- If the question is ambiguous in a way that changes the result, call ask_clarification.
  Ask at most one question, and offer options when you can.
- If a reasonable default exists, use it and state the assumption instead of asking.
- Otherwise call run_sql. After you see the results, call final_answer with a short
  summary of the key numbers and any assumptions.
- For follow-ups, keep the filters and definitions from earlier turns unless the user changes them.
- Today's date is {today}.

## Data Catalog
{catalog}

## Knowledge
{knowledge}

## Examples
{examples}
"""


def render_table(table: Table, include_pii: bool = False) -> str:
    """Compact text for one table; PII columns are left out unless `include_pii`."""
    header = f"### {table.table}" + (f"  ({table.grain})" if table.grain else "")
    lines = [header, table.description.strip()]
    for col in table.columns:
        if col.pii and not include_pii:
            continue
        line = f"- {col.name} {col.type}"
        if col.name in table.primary_key:
            line += " PK"
        if col.foreign_key:
            line += f" → {col.foreign_key}"
        if col.pii:
            line += " PII"
        if col.allowed_values:
            line += f" [{'|'.join(col.allowed_values)}]"
        if col.description:
            line += f" — {col.description}"
        lines.append(line)
    for rel in table.relationships:
        lines.append(f"Join: {rel.on}")
    return "\n".join(lines)


def render_knowledge(k: Knowledge) -> str:
    """Metrics, glossary, rules and ambiguous terms as plain text."""
    parts = []
    if k.metrics:
        parts.append("Metrics:\n" + "\n".join(
            f"- {m.name}: {m.definition}" + (f"\n  SQL: {m.sql}" if m.sql else "") for m in k.metrics
        ))  # fmt: skip
    if k.glossary:
        parts.append("Glossary:\n" + "\n".join(f"- {g.term}: {g.meaning}" for g in k.glossary))
    if k.rules:
        parts.append("Rules:\n" + "\n".join(f"- {r}" for r in k.rules))
    if k.ambiguities:
        parts.append(
            "Ambiguous terms (ask a clarifying question if the user uses one without saying which meaning):\n"
            + "\n".join(f"- {a.term}: {a.note}" for a in k.ambiguities)
        )
    return "\n\n".join(parts) or "(none)"


def pick_examples(examples: list[Example], question: str) -> list[Example]:
    """Up to MAX_EXAMPLES examples, ranked by word overlap with the question."""
    wanted = words(question)
    ranked = sorted(examples, key=lambda e: len(wanted & words(e.question)), reverse=True)
    return ranked[:MAX_EXAMPLES]


def render_examples(examples: list[Example]) -> str:
    if not examples:
        return "(none)"
    return "\n\n".join(f"Q: {e.question}\n```sql\n{e.sql.strip()}\n```" for e in examples)


def build_system_prompt(
    metadata: Metadata, dialect: str, question: str, history_text: str = ""
) -> str:
    """Fill the template; `history_text` is the recent conversation, used to pick tables."""
    tables = pick_tables(metadata.tables, f"{history_text} {question}")
    return SYSTEM_TEMPLATE.format(
        dialect=dialect,
        business_overview=metadata.knowledge.business_overview.strip() or "(not described)",
        today=date.today().isoformat(),
        catalog="\n\n".join(render_table(t, include_pii=settings.allow_pii) for t in tables),
        knowledge=render_knowledge(metadata.knowledge),
        examples=render_examples(pick_examples(metadata.examples, question)),
    )
