"""Database access: a SQL safety guard and a query runner."""

import time
from functools import cache

import pandas as pd
import sqlglot
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp
from sqlglot.errors import SqlglotError

from analytics_agent.config import settings


class UnsafeSQLError(ValueError):
    pass


class QueryError(RuntimeError):
    pass


WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
    exp.Alter, exp.TruncateTable, exp.Command, exp.Grant, exp.Set,
)  # fmt: skip
READ_ROOTS = (
    exp.Select,
    exp.SetOperation,
)  # SELECT, UNION, INTERSECT, EXCEPT (WITH hangs off a SELECT)


@cache
def get_engine() -> Engine:
    """Create the engine once; SQLite gets a per-query deadline."""
    engine = create_engine(settings.database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _no_writes_sqlite)
    return engine


def _no_writes_sqlite(dbapi_connection, _record) -> None:
    dbapi_connection.execute("PRAGMA query_only = ON")


def dialect() -> str:
    return get_engine().dialect.name


def validate_sql(sql: str, max_rows: int | None = None) -> str:
    """Return a safe single SELECT with a LIMIT, or raise UnsafeSQLError."""
    max_rows = max_rows or settings.max_rows
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect()) if s is not None]
    except SqlglotError as e:
        raise UnsafeSQLError(f"Could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, READ_ROOTS):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    if tree.find(*WRITE_NODES):
        raise UnsafeSQLError("Write or DDL statements are not allowed.")
    if not tree.args.get("limit"):
        tree = tree.limit(max_rows)
    return tree.sql(dialect=dialect())


def format_sql(sql: str) -> str:
    """Pretty-print SQL for display; unparseable SQL is returned unchanged."""
    try:
        return sqlglot.transpile(sql, read=dialect(), write=dialect(), pretty=True)[0]
    except SqlglotError:
        return sql


def run_query(sql: str) -> pd.DataFrame:
    """Run a validated query with a timeout and return the rows."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            _set_deadline(conn, settings.query_timeout_seconds)
            return pd.read_sql_query(text(sql), conn)
    except (SQLAlchemyError, pd.errors.DatabaseError) as e:
        # pandas wraps the SQLAlchemy error, which wraps the driver's message
        cause = e.__cause__ if isinstance(e, pd.errors.DatabaseError) else e
        raise QueryError(str(getattr(cause, "orig", None) or cause)) from e


def _set_deadline(conn, seconds: int) -> None:
    """Abort long queries; SQLite via a progress handler, Postgres via statement_timeout."""
    name = dialect()
    if name == "sqlite":
        deadline = time.monotonic() + seconds
        conn.connection.dbapi_connection.set_progress_handler(
            lambda: time.monotonic() > deadline, 10_000
        )
    elif name == "postgresql":
        conn.execute(text(f"SET statement_timeout = {int(seconds) * 1000}"))
