"""Pydantic models for the semantic layer YAML, plus loading and table selection."""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class MetadataError(RuntimeError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Column(Strict):
    name: str
    type: str
    description: str = ""
    foreign_key: str | None = None
    allowed_values: list[str] = []
    pii: bool = False
    event_time: bool = False  # the date the record belongs to; used by the date guardrail
    event_time_via_fk: bool = False  # no date of its own: use the table this foreign key points to
    individual_id: bool = (
        False  # identifies one person (an id); used by the individual-data guardrail
    )


class Relationship(Strict):
    to_table: str
    on: str

    @model_validator(mode="before")
    @classmethod
    def fix_yaml_boolean_key(cls, data):
        """YAML 1.1 reads an unquoted `on:` key as True."""
        if isinstance(data, dict) and True in data:
            data = {**data, "on": data[True]}
            del data[True]
        return data


class Table(Strict):
    table: str
    description: str
    grain: str = ""
    primary_key: list[str] = []
    tags: list[str] = []
    columns: list[Column]
    relationships: list[Relationship] = []
    individual_level: bool = False  # one row per person


class AppInfo(Strict):
    title: str = "Analytics Agent"
    subtitle: str = "Ask a question about your data"
    starter_questions: list[str] = []


class Metric(Strict):
    name: str
    definition: str
    sql: str = ""


class GlossaryTerm(Strict):
    term: str
    meaning: str


class Ambiguity(Strict):
    term: str
    note: str


class Knowledge(Strict):
    app: AppInfo = AppInfo()
    business_overview: str = ""
    metrics: list[Metric] = []
    glossary: list[GlossaryTerm] = []
    rules: list[str] = []
    ambiguities: list[Ambiguity] = []


class Example(Strict):
    question: str
    sql: str


class Examples(Strict):
    examples: list[Example] = []


class Metadata(Strict):
    tables: list[Table]
    knowledge: Knowledge
    examples: list[Example]


def _read(path: Path, model: type[BaseModel]):
    """Parse one YAML file into a model, naming the file and field on failure."""
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return model.model_validate(data)
    except FileNotFoundError:
        raise MetadataError(f"{path}: file not found") from None
    except yaml.YAMLError as e:
        raise MetadataError(f"{path}: invalid YAML: {e}") from e
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        raise MetadataError(f"{path}: {problems}") from e


def load_metadata(folder: Path) -> Metadata:
    """Load and validate every YAML file in the semantic layer folder."""
    catalog_files = sorted((folder / "data_catalog").glob("*.yaml"))
    if not catalog_files:
        raise MetadataError(f"{folder / 'data_catalog'}: no table YAML files found")
    return Metadata(
        tables=[_read(path, Table) for path in catalog_files],
        knowledge=_read(folder / "knowledge.yaml", Knowledge),
        examples=_read(folder / "examples.yaml", Examples).examples,
    )


def words(text: str) -> set[str]:
    """Lowercase word set, used for simple overlap matching."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def pick_tables(tables: list[Table], text: str, limit: int = 20) -> list[Table]:
    """Return all tables if few; else those sharing words with the text, plus their relationships."""
    if len(tables) <= limit:
        return tables
    wanted = words(text)

    def matches(t: Table) -> bool:
        table_words = words(
            " ".join([t.table, t.description, *t.tags, *(c.name for c in t.columns)])
        )
        return bool(wanted & table_words)

    chosen = {t.table for t in tables if matches(t)}
    chosen |= {r.to_table for t in tables if t.table in chosen for r in t.relationships}
    return [t for t in tables if t.table in chosen]
