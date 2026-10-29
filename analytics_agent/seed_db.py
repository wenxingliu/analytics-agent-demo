"""Builds the demo database by running semantic_layer/seed.sql."""

from pathlib import Path

import sqlglot
from sqlalchemy import create_engine, make_url, text

from analytics_agent.config import settings


def main() -> None:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    script = (settings.semantic_layer_path / "seed.sql").read_text()
    statements = [s for s in sqlglot.parse(script, dialect=url.get_backend_name()) if s is not None]
    # A separate engine from db.get_engine(), which is query-only
    with create_engine(url).begin() as conn:
        for statement in statements:
            conn.execute(text(statement.sql(dialect=url.get_backend_name())))
    print(f"Seeded {settings.database_url} ({len(statements)} statements).")


if __name__ == "__main__":
    main()
