import re
from pathlib import Path

import yaml

from analytics_agent.config import settings

ALLOWLIST = {
    "data",
    "name",
    "type",
    "date",
    "sales",
}  # generic words that may appear in code
CODE = Path(__file__).resolve().parent.parent / "analytics_agent"


def domain_terms() -> set[str]:
    folder = settings.semantic_layer_path
    terms = {p.stem for p in (folder / "data_catalog").glob("*.yaml")}
    knowledge = yaml.safe_load((folder / "knowledge.yaml").read_text())
    terms |= {m["name"] for m in knowledge.get("metrics", [])}
    terms |= {g["term"] for g in knowledge.get("glossary", [])}
    return {t.lower() for t in terms} - ALLOWLIST


def test_no_domain_words_in_code():
    terms = domain_terms()
    assert terms, "expected some domain terms to check"
    for path in CODE.glob("*.py"):
        text = path.read_text().lower()
        for term in terms:
            assert not re.search(rf"\b{re.escape(term)}\b", text), f"'{term}' found in {path.name}"
