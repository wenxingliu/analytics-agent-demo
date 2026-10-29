import pytest
from sqlalchemy import create_engine

from analytics_agent import db
from analytics_agent.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    original = settings.database_url
    url = f"sqlite:///{tmp_path / 'test.db'}"
    with create_engine(
        url
    ).begin() as conn:  # the app engine is query-only, so build the table here
        conn.exec_driver_sql("CREATE TABLE table_a (col_x INTEGER)")
    object.__setattr__(settings, "database_url", url)  # settings is frozen
    db.get_engine.cache_clear()
    yield
    object.__setattr__(settings, "database_url", original)
    db.get_engine.cache_clear()


@pytest.mark.parametrize("sql", [
    "INSERT INTO table_a VALUES (1)",
    "UPDATE table_a SET col_x = 1",
    "DELETE FROM table_a",
    "DROP TABLE table_a",
    "CREATE TABLE table_b (col_y INTEGER)",
    "SELECT 1; SELECT 2",
    "WITH t AS (SELECT 1) DELETE FROM table_a",
    "SELEC nonsense (",
])  # fmt: skip
def test_guard_blocks_unsafe_sql(sql):
    with pytest.raises(db.UnsafeSQLError):
        db.validate_sql(sql)


def test_guard_adds_limit_to_select_and_union():
    assert "LIMIT 7" in db.validate_sql("SELECT col_x FROM table_a", max_rows=7)
    assert "LIMIT 7" in db.validate_sql("SELECT 1 UNION SELECT 2", max_rows=7)


def test_guard_keeps_existing_limit_and_ctes():
    sql = db.validate_sql(
        "WITH t AS (SELECT col_x FROM table_a) SELECT * FROM t LIMIT 3", max_rows=7
    )
    assert "LIMIT 3" in sql and "LIMIT 7" not in sql


def test_run_query_returns_rows_and_reports_errors():
    assert len(db.run_query("SELECT 1 AS col_x")) == 1
    with pytest.raises(db.QueryError):
        db.run_query("SELECT missing FROM table_a")


def test_format_sql_is_multiline_and_tolerates_bad_sql():
    assert "\n" in db.format_sql(
        "SELECT col_x, COUNT(*) FROM table_a WHERE col_x > 1 GROUP BY col_x"
    )
    assert db.format_sql("SELEC nonsense (") == "SELEC nonsense ("
