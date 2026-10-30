import pytest

from analytics_agent import db
from analytics_agent.config import settings
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
