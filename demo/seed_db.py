"""Builds the demo database by running demo/seed.sql."""

from pathlib import Path

import sqlglot
from sqlalchemy import create_engine, make_url, text

from analytics_agent.config import settings


def seed(database_url: str) -> int:
    """Run seed.sql against the database and return the number of statements."""
    url = make_url(database_url)
    dialect = url.get_backend_name()
    if dialect == "sqlite" and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    script = (Path(__file__).parent / "seed.sql").read_text()
    statements = [s for s in sqlglot.parse(script, dialect=dialect) if s is not None]
    # A separate engine from db.get_engine(), which is query-only
    with create_engine(url).begin() as conn:
        for statement in statements:
            conn.execute(text(statement.sql(dialect=dialect)))
    return len(statements)


def main() -> None:
    count = seed(settings.database_url)
    print(f"Seeded {settings.database_url} ({count} statements).")


if __name__ == "__main__":
    main()
