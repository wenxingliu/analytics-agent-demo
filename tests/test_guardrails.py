import pytest

from analytics_agent.config import ConfigError, Guardrails
from analytics_agent.guardrails import GuardrailError, enforce, validate_config
from analytics_agent.metadata import Knowledge, Metadata, Table

OFF = Guardrails(min_date=None, no_individual_data=False, no_pii=False)


def col(name: str, **flags) -> dict:
    return {"name": name, "type": "TEXT", **flags}


@pytest.fixture
def metadata() -> Metadata:
    people = Table(
        table="table_p",
        description="people",
        individual_level=True,
        columns=[
            col("person_id", individual_id=True),
            col("person_nm", pii=True),
            col("grp_x"),
        ],
    )
    events = Table(
        table="table_e",
        description="events",
        columns=[
            col("e_id"),
            col("person_id", individual_id=True),
            col("ts_e", event_time=True),
            col("amt"),
        ],
    )
    lines = Table(
        table="table_l",
        description="event lines",
        columns=[col("e_id", foreign_key="table_e.e_id", event_time_via_fk=True), col("qty")],
    )
    return Metadata(tables=[people, events, lines], knowledge=Knowledge(), examples=[])


def run(sql: str, metadata: Metadata, **rails) -> str:
    return enforce(sql, metadata, "sqlite", Guardrails(**{**OFF.__dict__, **rails}))


# --- PII ---


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT person_nm FROM table_p",
        "SELECT p.person_nm FROM table_p p",
        "SELECT grp_x, COUNT(*) FROM table_p WHERE person_nm = 'x' GROUP BY 1",
        "SELECT * FROM table_p",
        "SELECT p.* FROM table_p p",
    ],
)
def test_pii_is_blocked(sql, metadata):
    with pytest.raises(GuardrailError, match="PII"):
        run(sql, metadata, no_pii=True)


def test_pii_allowed_when_guardrail_off_or_not_touched(metadata):
    run("SELECT person_nm FROM table_p", metadata, no_pii=False)
    run("SELECT COUNT(*) FROM table_p", metadata, no_pii=True)
    run("SELECT * FROM table_e", metadata, no_pii=True)


# --- Individual-level data ---


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT person_id FROM table_e",
        "SELECT person_id, SUM(amt) FROM table_e GROUP BY person_id",
        "SELECT SUM(amt) FROM table_e GROUP BY person_id",
        "SELECT SUM(amt) FROM table_e GROUP BY 1, person_id",
        "SELECT grp_x FROM table_p",
        "SELECT * FROM table_p",
        "SELECT MAX(person_id) FROM table_e",
        "SELECT SUM(amt) FROM table_e WHERE person_id = 7",
        "SELECT SUM(amt) FROM table_e WHERE person_id IN (1, 2)",
        "WITH t AS (SELECT person_id, SUM(amt) AS s FROM table_e GROUP BY 1) SELECT * FROM t",
        "WITH t AS (SELECT person_id AS who FROM table_e) SELECT who FROM t",
        "SELECT s FROM (SELECT person_id, SUM(amt) AS s FROM table_e GROUP BY 1) ORDER BY s DESC LIMIT 5",
        "SELECT person_id FROM table_e UNION SELECT person_id FROM table_e",
    ],
)
def test_individual_data_is_blocked(sql, metadata):
    with pytest.raises(GuardrailError):
        run(sql, metadata, no_individual_data=True)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(DISTINCT person_id) FROM table_e",
        "SELECT grp_x, COUNT(*) FROM table_p GROUP BY grp_x",
        "SELECT p.grp_x, SUM(e.amt) FROM table_e e JOIN table_p p ON p.person_id = e.person_id GROUP BY 1",
        "SELECT AVG(n) FROM (SELECT person_id, COUNT(*) AS n FROM table_e GROUP BY person_id)",
        "WITH t AS (SELECT person_id, SUM(amt) AS s FROM table_e GROUP BY 1) SELECT AVG(s), COUNT(*) FROM t",
        "SELECT e_id, amt FROM table_e",
    ],
)
def test_aggregates_are_allowed(sql, metadata):
    run(sql, metadata, no_individual_data=True)


def test_individual_guardrail_off_allows_rows(metadata):
    run("SELECT person_id FROM table_e", metadata, no_individual_data=False)


# --- Date floor ---


def test_date_floor_filters_dated_table_and_keeps_alias(metadata):
    sql = run("SELECT e.amt FROM table_e AS e WHERE e.amt > 1", metadata, min_date="2026-01-01")
    assert "FROM (SELECT * FROM table_e WHERE ts_e >= '2026-01-01') AS e" in sql


def test_date_floor_follows_foreign_key_for_undated_table(metadata):
    sql = run("SELECT SUM(qty) FROM table_l", metadata, min_date="2026-01-01")
    assert "e_id IN (SELECT e_id FROM table_e WHERE ts_e >= '2026-01-01')" in sql


def test_date_floor_covers_joins_ctes_and_subqueries(metadata):
    sql = run(
        "WITH t AS (SELECT e_id FROM table_e) SELECT COUNT(*) FROM t JOIN table_l USING (e_id) "
        "WHERE e_id IN (SELECT e_id FROM table_e)",
        metadata,
        min_date="2026-01-01",
    )
    assert sql.count("ts_e >= '2026-01-01'") == 3  # CTE, the lines' parent check, and the subquery


def test_date_floor_leaves_undated_tables_alone(metadata):
    sql = run("SELECT COUNT(*) FROM table_p", metadata, min_date="2026-01-01")
    assert "2026" not in sql


def test_date_floor_really_hides_old_rows(metadata, tmp_path):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE table_e (e_id INT, person_id INT, ts_e TEXT, amt INT)"))
        conn.execute(text("CREATE TABLE table_l (e_id INT, qty INT)"))
        conn.execute(
            text(
                "INSERT INTO table_e VALUES (1, 1, '2025-12-31 23:00:00', 10), (2, 1, '2026-01-01 00:00:00', 20)"
            )
        )
        conn.execute(text("INSERT INTO table_l VALUES (1, 5), (2, 7)"))
        sql_e = run("SELECT SUM(amt) FROM table_e", metadata, min_date="2026-01-01")
        sql_l = run("SELECT SUM(qty) FROM table_l", metadata, min_date="2026-01-01")
        assert conn.execute(text(sql_e)).scalar() == 20
        assert conn.execute(text(sql_l)).scalar() == 7


# --- Config ---


def test_validate_config_needs_flags_for_active_guardrails(metadata):
    bare = Metadata(
        tables=[Table(table="table_z", description="z", columns=[col("c")])],
        knowledge=Knowledge(),
        examples=[],
    )
    with pytest.raises(ConfigError, match="event_time"):
        validate_config(bare, Guardrails(min_date="2026-01-01", no_individual_data=False))
    with pytest.raises(ConfigError, match="INDIVIDUAL"):
        validate_config(bare, Guardrails(no_individual_data=True))
    validate_config(metadata, Guardrails(min_date="2026-01-01"))
    validate_config(bare, OFF)
