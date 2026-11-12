from analytics_agent.metadata import Table
from analytics_agent.prompts import render_table


def table() -> Table:
    return Table(
        table="table_a",
        description="A table.",
        columns=[
            {"name": "col_x", "type": "INTEGER"},
            {"name": "col_secret", "type": "VARCHAR", "pii": True},
        ],
    )


def test_pii_columns_hidden_by_default():
    text = render_table(table())
    assert "col_x" in text and "col_secret" not in text


def test_pii_columns_shown_and_tagged_when_allowed():
    text = render_table(table(), include_pii=True)
    assert "- col_secret VARCHAR PII" in text
