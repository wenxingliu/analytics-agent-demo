import pytest

from demo import seed_db
from evals import reference
from evals.grading import load_cases, matches_expected, numbers_in


def test_every_case_has_the_three_fields():
    cases = load_cases()
    assert len(cases) >= 20
    assert all(c.query and c.expected_response for c in cases)
    assert len({c.query for c in cases}) == len(cases)
    assert any(c.exact_match for c in cases) and any(not c.exact_match for c in cases)


def test_a_case_with_an_extra_field_is_rejected(tmp_path):
    bad = tmp_path / "cases.yaml"
    bad.write_text("- query: q\n  exact_match: true\n  expected_response: '1'\n  category: x\n")
    with pytest.raises(ValueError, match="exactly"):
        load_cases(bad)


def test_exact_match_must_be_a_bool(tmp_path):
    bad = tmp_path / "cases.yaml"
    bad.write_text("- query: q\n  exact_match: 'yes'\n  expected_response: '1'\n")
    with pytest.raises(TypeError, match="true or false"):
        load_cases(bad)


def test_expected_numbers_match_the_reference_sql(tmp_path):
    url = f"sqlite:///{tmp_path / 'ref.db'}"
    seed_db.seed(url)
    answers = reference.compute(url)
    numeric = {c.query: c.expected_response for c in load_cases() if c.exact_match}
    assert numeric == answers


@pytest.mark.parametrize(
    ("reply", "expected", "ok"),
    [
        ("GMV was **$47,903.60** in March.", "47903.60", True),
        ("About $47,904.", "47903.60", True),  # rounded to the precision the reply shows
        ("GMV was $47,903.5.", "47903.60", False),  # wrong at the precision shown
        ("There were 5 orders.", "6", False),
        ("There were 6 orders, 12 items.", "6", True),
        ("Total is 1,234.", "1234", True),
        ("The Living Room group shipped the most.", "Living Room", True),
        ("The Bath group shipped the most.", "Living Room", False),
        ("No numbers here", "6", False),
    ],
)
def test_matches_expected(reply, expected, ok):
    assert matches_expected(reply, expected) is ok


def test_numbers_in_strips_separators_and_trailing_punctuation():
    assert numbers_in("Revenue: $1,234,567.89, then 42.") == ["1234567.89", "42"]
