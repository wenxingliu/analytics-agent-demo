"""Runs the evals on several models and writes a side-by-side comparison report, with cost.

Usage: python -m evals.compare MODEL [MODEL ...] [--judge-provider NAME] [--judge-model ID]
                                                 [-k TEXT] [--workers N] [--parallel N] [--out DIR]

Each model runs in its own process via evals.report (settings are read once per process), so every
model gets its own throwaway database, the same judge and every guardrail on. The output folder
holds compare.md, one <model>.md report per model and the raw <model>.json results.
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from evals.cost import load_pricing
from evals.report import REPORTS_DIR, cell, git_version, usd
from evals.run import GUARDRAIL_ENV, JUDGE_MODEL, JUDGE_PROVIDER


def safe(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def run_model(model: str, folder: Path, args: argparse.Namespace) -> dict | None:
    """Run evals.report for one model; its JSON results, or None if it crashed."""
    command = [
        sys.executable,
        "-m",
        "evals.report",
        model,
        "--judge-provider",
        args.judge_provider,
        "--judge-model",
        args.judge_model,
        "--workers",
        str(args.workers),
        "--out",
        str(folder / f"{safe(model)}.md"),
        "--json",
        str(folder / f"{safe(model)}.json"),
    ]
    if args.k:
        command += ["-k", args.k]
    done = subprocess.run(
        command, capture_output=True, text=True, check=False
    )  # exit 1 = some cases failed
    output = (done.stdout + done.stderr).strip().splitlines()
    print(f"[{model}] {output[-1] if output else 'no output'}", flush=True)
    path = folder / f"{safe(model)}.json"
    if not path.exists():
        (folder / f"{safe(model)}.log").write_text(done.stdout + done.stderr)
        return None
    return json.loads(path.read_text())


def pct(passed: int, total: int) -> str:
    return f"{passed}/{total} ({passed / total:.0%})" if total else "–"


def render(runs: dict[str, dict | None], judge: str, started: datetime) -> str:
    ok = {m: r for m, r in runs.items() if r}
    pricing = load_pricing()

    def passed(run: dict, exact: bool | None = None) -> tuple[int, int]:
        cases = [c for c in run["cases"] if exact is None or c["exact_match"] == exact]
        return sum(c["passed"] for c in cases), len(cases)

    ranked = sorted(ok, key=lambda m: (-passed(ok[m])[0], ok[m]["agent_cost"] or 0))
    n_cases = len(next(iter(ok.values()))["cases"]) if ok else 0
    out = [
        "# Eval comparison",
        "",
        "| | |",
        "|---|---|",
        f"| Models | {', '.join(f'`{m}`' for m in runs)} |",
        f"| Judge | {judge} |",
        f"| Run at | {started:%Y-%m-%d %H:%M} |",
        f"| Code version | {git_version()} |",
        f"| Cases per model | {n_cases} |",
        "",
        (
            "Every model ran the same cases on its own fresh copy of the demo database, with every "
            "guardrail on (no PII, no individual-level data, data from "
            f"{GUARDRAIL_ENV['GUARDRAIL_MIN_DATE']}). Each case ran once per model, so a difference of "
            "one or two cases is within noise."
        ),
        "",
    ]
    crashed = [m for m, r in runs.items() if not r]
    if crashed:
        out += [
            f"**Did not finish:** {', '.join(f'`{m}`' for m in crashed)} (see the .log files).",
            "",
        ]

    out += [
        "## Leaderboard",
        "",
        (
            "Ranked by cases passed, then by cost. Cost is the model under test only, at list "
            "price; the judge's cost is shown separately."
        ),
        "",
        "| Rank | Model | All cases | Numeric | Behavior | Avg time / case | Model cost | Cost / case | Cost / passed case | Judge cost |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, m in enumerate(ranked, 1):
        r = ok[m]
        times = [c["seconds"] for c in r["cases"]]
        out.append(
            f"| {rank} | [`{m}`]({safe(m)}.md) | **{pct(*passed(r))}** | {pct(*passed(r, True))} "
            f"| {pct(*passed(r, False))} | {sum(times) / len(times):.1f} s | {usd(r['agent_cost'])} "
            f"| {usd(r['agent_cost_per_case'])} | {usd(r['agent_cost_per_pass'])} | {usd(r['judge_cost'])} |"
        )
    out.append("")

    if ok:
        out += [
            "## Tokens",
            "",
            "| Model | Calls | Uncached input | Cached input | Output |",
            "|---|---|---|---|---|",
        ]
        for m in ranked:
            u = ok[m]["agent_usage"].get(m, {})
            out.append(
                f"| `{m}` | {u.get('calls', 0):,} | {u.get('input', 0):,} | "
                f"{u.get('cached_input', 0):,} | {u.get('output', 0):,} |"
            )
        out.append("")

    if ok:
        queries = [c["query"] for c in next(iter(ok.values()))["cases"]]
        by_model = {m: {c["query"]: c for c in ok[m]["cases"]} for m in ranked}
        out += [
            "## Case by case",
            "",
            "✅ passed, ❌ failed. Cases are sorted with the ones most models failed first.",
            "",
            "| Question | Type | " + " | ".join(f"`{m}`" for m in ranked) + " | Passed by |",
            "|---|---|" + "---|" * len(ranked) + "---|",
        ]

        def n_passed(q: str) -> int:
            return sum(by_model[m][q]["passed"] for m in ranked if q in by_model[m])

        for q in sorted(queries, key=n_passed):
            first = next(by_model[m][q] for m in ranked if q in by_model[m])
            marks = [
                ("✅" if by_model[m][q]["passed"] else "❌") if q in by_model[m] else "–"
                for m in ranked
            ]
            kind = "numeric" if first["exact_match"] else "behavior"
            out.append(
                f"| {cell(q, 90)} | {kind} | "
                + " | ".join(marks)
                + f" | {n_passed(q)}/{len(ranked)} |"
            )
        out.append("")

        out += ["## Failures by model", ""]
        for m in ranked:
            fails = [c for c in ok[m]["cases"] if not c["passed"]]
            out += [f"### `{m}`: {len(fails)} failed", ""]
            out += [f"- **{cell(c['query'], 100)}** — {cell(c['reason'], 220)}" for c in fails] or [
                "None."
            ]
            out.append("")

    used = sorted({m for r in ok.values() for m in (*r["agent_usage"], *r["judge_usage"])})
    out += [
        "## Prices used",
        "",
        "USD per 1M tokens, from `evals/pricing.yaml` (list prices; see that file for sources and date).",
        "",
        "| Model | Input | Cached input | Output |",
        "|---|---|---|---|",
    ]
    for m in used:
        p = pricing.get(m)
        out.append(
            f"| `{m}` | {p['input']:.2f} | {p['cached_input']:.2f} | {p['output']:.2f} |"
            if p
            else f"| `{m}` | no price | | |"
        )
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("models", nargs="+", help="model ids to compare")
    parser.add_argument("--judge-provider", default=JUDGE_PROVIDER)
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("-k", help="only run cases whose query contains this text")
    parser.add_argument("--workers", type=int, default=4, help="cases in parallel per model")
    parser.add_argument("--parallel", type=int, default=2, help="models run at the same time")
    parser.add_argument(
        "--out", type=Path, help="output folder (default: evals/reports/<date>-compare/)"
    )
    args = parser.parse_args()

    started = datetime.now()
    folder = args.out or REPORTS_DIR / f"{started:%Y%m%d-%H%M}-compare"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Comparing {len(args.models)} models, judged by {args.judge_model}. Output: {folder}")
    with ThreadPoolExecutor(args.parallel) as pool:
        results = list(pool.map(lambda m: run_model(m, folder, args), args.models))
    runs = dict(zip(args.models, results, strict=True))
    judge = f"{args.judge_provider} / {args.judge_model}"
    (folder / "compare.md").write_text(render(runs, judge, started))
    print(f"Comparison: {folder / 'compare.md'}")


if __name__ == "__main__":
    main()
