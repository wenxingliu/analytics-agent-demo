"""Loading eval cases and grading numeric answers. No LLM and no app imports, so tests can use it."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

CASES_FILE = Path(__file__).parent / "cases.yaml"
FIELDS = {"query", "exact_match", "expected_response"}
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Case:
    query: str
    exact_match: bool
    expected_response: str


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    """Read the cases, failing with the case number if one is malformed."""
    cases = []
    for i, raw in enumerate(yaml.safe_load(path.read_text()), 1):
        if set(raw) != FIELDS:
            raise ValueError(f"{path.name} case {i}: fields must be exactly {sorted(FIELDS)}")
        if not isinstance(raw["exact_match"], bool):
            raise TypeError(f"{path.name} case {i}: exact_match must be true or false")
        cases.append(Case(raw["query"], raw["exact_match"], str(raw["expected_response"])))
    return cases


def numbers_in(text: str) -> list[str]:
    """Number tokens in a reply, without thousands separators ('$1,234.50' -> '1234.50')."""
    return [token.rstrip(",").replace(",", "") for token in NUMBER.findall(text)]


def matches_expected(reply_text: str, expected: str) -> bool:
    """True if the reply contains the expected number, at the precision the reply shows.

    A reply saying $12,346 matches 12345.67; one saying 12,345.6 does not. Non-numeric
    expectations (names) match as a case-insensitive substring.
    """
    try:
        want = Decimal(expected.replace(",", ""))
    except ArithmeticError:
        return expected.lower() in reply_text.lower()
    for token in numbers_in(reply_text):
        shown = Decimal(token)
        places = Decimal(1).scaleb(-(len(token.split(".")[1]) if "." in token else 0))
        if want.quantize(places, rounding=ROUND_HALF_UP) == shown:
            return True
    return False
