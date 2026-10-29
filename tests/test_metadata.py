import pytest

from analytics_agent.config import settings
from analytics_agent.metadata import MetadataError, Table, load_metadata, pick_tables


def table(name: str, description: str, **kwargs) -> Table:
    return Table(
        table=name,
        description=description,
        columns=[{"name": "col_x", "type": "INTEGER"}],
        **kwargs,
    )


def test_semantic_layer_loads():
    metadata = load_metadata(settings.semantic_layer_path)
    assert metadata.tables and metadata.knowledge and metadata.examples


def test_broken_yaml_names_file_and_field(tmp_path):
    (tmp_path / "data_catalog").mkdir()
    (tmp_path / "data_catalog" / "table_a.yaml").write_text("table: table_a\ncolumns: []\n")
    with pytest.raises(MetadataError, match=r"table_a\.yaml.*description"):
        load_metadata(tmp_path)


def test_pick_tables_returns_all_when_few():
    tables = [table("table_a", "alpha"), table("table_b", "beta")]
    assert pick_tables(tables, "anything", limit=5) == tables


def test_pick_tables_matches_words_and_follows_relationships():
    rel = [{"to_table": "table_c", "on": "table_a.col_x = table_c.col_x"}]
    tables = [
        table("table_a", "alpha things", relationships=rel),
        table("table_b", "beta things"),
        table("table_c", "gamma things"),
    ]
    picked = pick_tables(tables, "show alpha", limit=2)
    assert [t.table for t in picked] == ["table_a", "table_c"]
