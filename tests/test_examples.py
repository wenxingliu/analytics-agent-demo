import pytest

from analytics_agent import db, guardrails
from analytics_agent.config import Guardrails, settings
from analytics_agent.metadata import load_metadata
from demo import seed_db


@pytest.fixture
def seeded_db(tmp_path):
    original = settings.database_url
    url = f"sqlite:///{tmp_path / 'test.db'}"
    seed_db.seed(url)
    object.__setattr__(settings, "database_url", url)  # settings is frozen
    db.get_engine.cache_clear()
    yield
    object.__setattr__(settings, "database_url", original)
    db.get_engine.cache_clear()


def test_every_example_runs_and_returns_rows(seeded_db):
    for example in load_metadata(settings.semantic_layer_path).examples:
        rows = db.run_query(db.validate_sql(example.sql))
        assert len(rows) > 0, example.question


def test_every_catalog_table_and_column_exists(seeded_db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_engine())
    for table in load_metadata(settings.semantic_layer_path).tables:
        actual = {c["name"] for c in inspector.get_columns(table.table)}
        assert {c.name for c in table.columns} == actual, table.table


def test_examples_pass_all_guardrails_and_only_see_the_allowed_dates(seeded_db):
    metadata = load_metadata(settings.semantic_layer_path)
    rails = Guardrails(min_date="2026-01-01", no_individual_data=True, no_pii=True)
    guardrails.validate_config(metadata, rails)
    for example in metadata.examples:
        sql = guardrails.enforce(db.validate_sql(example.sql), metadata, db.dialect(), rails)
        assert len(db.run_query(sql)) > 0, example.question


def test_guardrails_on_the_real_catalog(seeded_db):
    metadata = load_metadata(settings.semantic_layer_path)
    rails = Guardrails(min_date="2026-01-01", no_individual_data=True, no_pii=True)

    def check(sql: str) -> str:
        return guardrails.enforce(db.validate_sql(sql), metadata, db.dialect(), rails)

    for blocked in [
        "SELECT eml_addr FROM dim_cust",
        "SELECT cust_id, SUM(gross_amt_lcl) FROM fct_ord_hdr GROUP BY cust_id",
        "SELECT cust_tier_cd, ctry_cd FROM dim_cust",
        "SELECT SUM(gross_amt_lcl) FROM fct_ord_hdr WHERE cust_id = 5",
    ]:
        with pytest.raises(guardrails.GuardrailError):
            check(blocked)

    earliest = db.run_query(check("SELECT MIN(ord_ts) AS first_order FROM fct_ord_hdr"))
    assert earliest["first_order"][0] >= "2026-01-01"
    lines = db.run_query(check("SELECT COUNT(*) AS n FROM fct_ord_ln"))["n"][0]
    all_lines = db.run_query("SELECT COUNT(*) AS n FROM fct_ord_ln")["n"][0]
    assert 0 < lines < all_lines
