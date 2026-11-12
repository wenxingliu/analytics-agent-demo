"""Runs every eval case on one model and writes a Markdown report.

Usage: python -m evals.report MODEL [--provider NAME] [--judge-provider NAME] [--judge-model ID]
                                    [-k TEXT] [--workers N] [--out PATH]

The provider is found from the model id (the configured provider that lists it) unless --provider
is given. Grading is the same as evals.run: a fixed judge model, every guardrail on, a throwaway
copy of the demo database. The report goes to evals/reports/<date>-<model>.md by default.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from evals.cost import add_usage, cost, load_pricing
from evals.run import GUARDRAIL_ENV, Result, add_common_args, run_cases

REPORTS_DIR = Path(__file__).parent / "reports"


def git_version() -> str:
    """Short commit id, with '+ local changes' if the working tree is dirty."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit} + local changes" if dirty else commit


def cell(text: str, limit: int = 120) -> str:
    """Text made safe for one Markdown table cell."""
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def rate(results: list[Result]) -> str:
    if not results:
        return "–"
    passed = sum(r.passed for r in results)
    return f"{passed}/{len(results)} ({passed / len(results):.0%})"


def usd(value: float | None) -> str:
    if value is None:
        return "no price"
    return f"${value:.4f}" if value < 1 else f"${value:.2f}"


def tokens(usage: dict) -> str:
    total = add_usage(*({"all": c} for c in usage.values())).get("all", {})
    if not total:
        return "–"
    return (
        f"{total.get('input', 0):,} in + {total.get('cached_input', 0):,} cached + "
        f"{total.get('output', 0):,} out ({total.get('calls', 0)} calls)"
    )


def cost_summary(results: list[Result], pricing: dict) -> dict:
    """Totals for the report and for comparisons."""
    agent = add_usage(*(r.agent_usage for r in results))
    judge = add_usage(*(r.judge_usage for r in results))
    agent_cost, judge_cost = cost(agent, pricing), cost(judge, pricing)
    passed = sum(r.passed for r in results)
    return {
        "agent_usage": agent,
        "judge_usage": judge,
        "agent_cost": agent_cost,
        "judge_cost": judge_cost,
        "agent_cost_per_case": agent_cost / len(results)
        if agent_cost is not None and results
        else None,
        "agent_cost_per_pass": agent_cost / passed if agent_cost is not None and passed else None,
    }


def reply_lines(result: Result) -> list[str]:
    reply = result.reply
    lines = []
    if reply.text:
        lines.append(f"- **Answer:** {' '.join(reply.text.split())}")
    if reply.question:
        options = f" (options: {', '.join(reply.options)})" if reply.options else ""
        lines.append(f"- **Clarifying question:** {reply.question}{options}")
    if reply.error:
        lines.append(f"- **Error:** {' '.join(reply.error.split())}")
    if reply.sql:
        lines += [
            "- **Last SQL:**",
            "",
            "  ```sql",
            *[f"  {ln}" for ln in reply.sql.splitlines()],
            "  ```",
        ]
    else:
        lines.append("- **Last SQL:** none")
    return lines


def render(
    model_label: str,
    judge_label: str,
    results: list[Result],
    started: datetime,
    seconds: float,
    pricing: dict | None = None,
) -> str:
    pricing = load_pricing() if pricing is None else pricing
    costs = cost_summary(results, pricing)
    numeric = [r for r in results if r.case.exact_match]
    behavior = [r for r in results if not r.case.exact_match]
    failures = [r for r in results if not r.passed]
    times = [r.seconds for r in results]

    out = [
        f"# Eval report: {model_label}",
        "",
        "| | |",
        "|---|---|",
        f"| Model under test | {model_label} |",
        f"| Judge | {judge_label} |",
        f"| Run at | {started:%Y-%m-%d %H:%M} |",
        f"| Code version | {git_version()} |",
        f"| Cases | {len(results)} |",
        f"| Wall time | {seconds:.0f} s |",
        "",
        (
            "Every guardrail is on (no PII, no individual-level data, data from "
            f"{GUARDRAIL_ENV['GUARDRAIL_MIN_DATE']}). Each case runs once, so a single failure "
            "is worth a look, not necessarily a regression."
        ),
        "",
        "## Summary",
        "",
        "| | Passed |",
        "|---|---|",
        f"| **All cases** | **{rate(results)}** |",
        f"| Numeric answers | {rate(numeric)} |",
        f"| Behavior | {rate(behavior)} |",
        "",
    ]
    if times:
        out += [
            f"Agent time per case: average {sum(times) / len(times):.1f} s, slowest {max(times):.1f} s.",
            "",
        ]

    out += [
        "## Cost",
        "",
        "List prices from `evals/pricing.yaml`. The judge's cost is the price of grading, not of the model.",
        "",
        "| | Tokens | Cost |",
        "|---|---|---|",
        f"| Model under test | {tokens(costs['agent_usage'])} | **{usd(costs['agent_cost'])}** |",
        f"| Judge | {tokens(costs['judge_usage'])} | {usd(costs['judge_cost'])} |",
        f"| Model cost per case | | {usd(costs['agent_cost_per_case'])} |",
        f"| Model cost per passed case | | {usd(costs['agent_cost_per_pass'])} |",
        "",
    ]

    out += ["## Failures", ""]
    if not failures:
        out += ["None.", ""]
    for i, r in enumerate(failures, 1):
        kind = "numeric" if r.case.exact_match else "behavior"
        out += [
            f"### {i}. {r.case.query}",
            "",
            f"- **Type:** {kind}",
            f"- **Expected:** {' '.join(r.case.expected_response.split())}",
            *reply_lines(r),
            f"- **Why it failed:** {' '.join(r.reason.split())}",
            "",
        ]

    out += [
        "## All cases",
        "",
        "| # | Result | Type | Question | Time | Model cost |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        kind = "numeric" if r.case.exact_match else "behavior"
        out.append(
            f"| {i} | {'PASS' if r.passed else '**FAIL**'} | {kind} | {cell(r.case.query)} "
            f"| {r.seconds:.1f} s | {usd(cost(r.agent_usage, pricing))} |"
        )
    return "\n".join(out) + "\n"


def to_json(
    model: str, provider_label: str, judge_label: str, results: list[Result], seconds: float
) -> dict:
    """Machine-readable results, for evals.compare."""
    pricing = load_pricing()
    return {
        "model": model,
        "provider": provider_label,
        "judge": judge_label,
        "seconds": seconds,
        "code_version": git_version(),
        **cost_summary(results, pricing),
        "cases": [
            {
                "query": r.case.query,
                "exact_match": r.case.exact_match,
                "expected": r.case.expected_response,
                "passed": r.passed,
                "reason": r.reason,
                "seconds": r.seconds,
                "answer": r.reply.text or r.reply.question,
                "error": r.reply.error,
                "sql": r.reply.sql,
                "agent_usage": r.agent_usage,
                "judge_usage": r.judge_usage,
                "agent_cost": cost(r.agent_usage, pricing),
            }
            for r in results
        ],
    }


def default_path(model: str, started: datetime) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    return REPORTS_DIR / f"{started:%Y%m%d-%H%M}-{safe}.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model", help="model id to evaluate, e.g. gpt-6-sol")
    parser.add_argument("--provider", help="kimi or openai (default: found from the model id)")
    add_common_args(parser)
    parser.add_argument(
        "--out", type=Path, help="report path (default: evals/reports/<date>-<model>.md)"
    )
    parser.add_argument("--json", type=Path, help="also write the raw results as JSON here")
    args = parser.parse_args()

    started, clock = datetime.now(), time.monotonic()

    def announce(provider, judge_provider, n: int) -> None:
        print(
            f"Running {n} cases with {provider.label} / {provider.model}, "
            f"judged by {judge_provider.label} / {judge_provider.model}…"
        )

    provider, judge_provider, results = run_cases(
        args.provider,
        args.model,
        args.judge_provider,
        args.judge_model,
        args.k,
        args.workers,
        on_start=announce,
    )
    seconds = time.monotonic() - clock

    path = args.out or default_path(provider.model, started)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render(
            f"{provider.label} / {provider.model}",
            f"{judge_provider.label} / {judge_provider.model}",
            results,
            started,
            seconds,
        )
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = to_json(
            provider.model,
            provider.label,
            f"{judge_provider.label} / {judge_provider.model}",
            results,
            seconds,
        )
        args.json.write_text(json.dumps(data, indent=2))
    print(f"{rate(results)} passed. Report: {path}")
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
