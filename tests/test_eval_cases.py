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


def test_numeric_match_skips_the_judge_and_a_miss_asks_it(monkeypatch):
    from analytics_agent import llm
    from analytics_agent.agent import Reply
    from evals import run
    from evals.grading import Case

    calls = []

    def fake_judge(messages, name, schema, provider):
        calls.append(messages[0]["content"])
        return {"passed": False, "reason": "wrong value"}

    monkeypatch.setattr(llm, "chat_json", fake_judge)
    case = Case(query="How many?", exact_match=True, expected_response="290")
    assert run.grade(case, Reply(text="There are 290."), judge_provider=None) == (True, "")
    assert calls == []
    passed, reason = run.grade(case, Reply(text="There are 312."), judge_provider=None)
    assert not passed and "wrong value" in reason
    assert calls == [run.JUDGE_NUMBER_PROMPT]


def test_behavior_cases_always_go_to_the_judge(monkeypatch):
    from analytics_agent import llm
    from analytics_agent.agent import Reply
    from evals import run
    from evals.grading import Case

    monkeypatch.setattr(llm, "chat_json", lambda *a: {"passed": True, "reason": "ok"})
    case = Case(query="Hi", exact_match=False, expected_response="Declines politely.")
    assert run.grade(case, Reply(text="Sorry, I can't help with that."), judge_provider=None) == (
        True,
        "ok",
    )
    monkeypatch.setattr(llm, "chat_json", lambda *a: {})
    assert run.grade(case, Reply(text="..."), judge_provider=None)[0] is False


def test_report_lists_summary_failures_and_every_case():
    from datetime import datetime

    from analytics_agent.agent import Reply
    from evals.grading import Case
    from evals.report import render
    from evals.run import Result

    results = [
        Result(Case("How many?", True, "290"), Reply(text="290", sql="SELECT 1"), True, "", 1.0),
        Result(
            Case("A | B?", False, "Declines."), Reply(text="Sure!"), False, "did not decline", 2.0
        ),
    ]
    text = render("P / m", "J / j", results, datetime(2026, 1, 1), 3.0)
    assert "**1/2 (50%)**" in text
    assert "### 1. A | B?" in text and "did not decline" in text
    assert "| 2 | **FAIL** | behavior | A \\| B? | 2.0 s |" in text
