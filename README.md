# Analytics Agent

A text-to-SQL chat app. Ask a question in plain language; the agent asks a clarifying question if it needs to, writes SQL, runs it read-only and shows the results. Built with Streamlit and Kimi (Moonshot AI) through its OpenAI-compatible API. See `analytics-agent-design.md` for the design.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set a provider's key and model (see below)
python -m demo.seed_db
streamlit run analytics_agent/app.py
```

## Model providers

Both providers use the OpenAI-compatible chat API. Configure either or both in `.env`:

| Provider | Variables |
|---|---|
| Kimi (Moonshot) | `MOONSHOT_API_KEY`, optional `KIMI_MODEL`, optional `MOONSHOT_BASE_URL` (`https://api.moonshot.cn/v1` for China) |
| OpenAI | `OPENAI_API_KEY`, optional `OPENAI_MODEL`, `OPENAI_BASE_URL` |

A provider is available once its key is set. The sidebar has a **Provider** selector and a **Model** selector, which lists the models fetched from the provider's API (type a model id if the list cannot be fetched). The `*_MODEL` variable is just the default selection. You can change either at any point, even mid-conversation. `LLM_PROVIDER=kimi|openai` chooses which is selected first. Check each provider's docs for current model ids.

Tests and lint: `pytest` and `ruff check .`

## How it works

`app.py` (UI) → `agent.py` (loop over three tools: `ask_clarification`, `run_sql`, `final_answer`) → `prompts.py` + `metadata.py` (YAML → prompt), `llm.py` (Kimi or OpenAI), `db.py` (sqlglot guard + SQLAlchemy). SQL must be a single SELECT, gets a `LIMIT`, runs with a timeout, and on SQLite the connection is also `query_only`. For a real database, use a read-only user.

## Using it for another domain

The Python code knows nothing about the domain. Everything lives in `semantic_layer/`:

1. Replace `data_catalog/*.yaml` (one file per table), `knowledge.yaml` and `examples.yaml`. Section 6 of the design doc describes the format. `knowledge.yaml`'s `app` section sets the title, subtitle and starter questions.
2. Set `DATABASE_URL` to the new database (install its SQLAlchemy driver). `demo/` (`seed.sql`, `seed_db.py`) is only for building the demo database.
3. Run the app. No code changes.

`tests/test_no_domain_terms.py` fails if a table, metric or glossary term from `semantic_layer/` shows up in any `.py` file under `analytics_agent/`.

Mark sensitive columns with `pii: true`. With `GUARDRAIL_NO_PII=true` they are kept out of the prompt and blocked in queries; with it off they are included, tagged PII. Put terms that need a clarifying question under `ambiguities`.

## Guardrails

Three settings in `.env` limit what the agent can pull. The app's sidebar lists the ones that are on.

| Setting | Default | Effect |
|---|---|---|
| `GUARDRAIL_NO_PII` | `true` | Columns marked `pii: true` are hidden from the model and any query that uses them is rejected. Off: they are shown, tagged PII. |
| `GUARDRAIL_NO_INDIVIDUAL_DATA` | `true` | Aggregates only: no per-person rows, per-person grouping, or lookups of a single person. Uses the `individual_id`, `pii` and `individual_level` catalog flags. |
| `GUARDRAIL_MIN_DATE` | empty (off) | `YYYY-MM-DD`. Every dated table is filtered to rows on or after this date, using the `event_time` (or `event_time_via_fk`) catalog flags. |

Personal-data columns also identify a person, so `GUARDRAIL_NO_INDIVIDUAL_DATA` blocks them too: to return names or addresses, set both `GUARDRAIL_NO_PII` and `GUARDRAIL_NO_INDIVIDUAL_DATA` to `false`.

The guardrails are applied to the SQL itself before it runs, so they hold even if the model ignores its instructions.

## Evals

The evals run the real agent on a set of questions and score the replies with an LLM judge: a fixed model, OpenAI `gpt-6-luna` by default, separate from the model under test. They make live API calls, so they are separate from `pytest`.

**Prerequisites:** set up as in [Setup](#setup), with `OPENAI_API_KEY` in `.env` for the judge (plus a key for the provider under test, if different). The demo database does not need to be seeded; the runner builds its own.

**Run all cases:**

```bash
python -m evals.run
```

**Options:**

| Option | Meaning |
|---|---|
| `--provider kimi\|openai` | Provider to test (default: the first one configured in `.env`) |
| `--model <id>` | Model to test (default: the provider's `*_MODEL`, else the first model it lists) |
| `-k <text>` | Only run cases whose query contains this text, e.g. `-k revenue` |
| `--judge-provider kimi\|openai` | Provider of the judge model (default: `openai`) |
| `--judge-model <id>` | Judge model (default: `gpt-6-luna`) |
| `--workers <n>` | Cases to run in parallel (default 4) |

```bash
python -m evals.run --provider openai --model <id> -k refunds
```

**Report for one model:** runs every case on the model you name and writes a Markdown report: pass rates overall and by type, each failure with the expected answer, the reply, the SQL and the judge's reason, and a table of all cases with timings. The provider is found from the model id. Reports go to `evals/reports/` (git-ignored); `--out` writes elsewhere. It takes the same `--judge-*`, `-k` and `--workers` options.

```bash
python -m evals.report kimi-k3
```

**Comparing models:** runs the evals on several models, each in its own process with the same judge, and writes `compare.md` (leaderboard with pass rates and cost, token counts, a case-by-case grid and each model's failures) plus one report per model into `evals/reports/<date>-compare/`.

```bash
python -m evals.compare kimi-k2.6 kimi-k3 kimi-k3.1-pro --parallel 2
```

**Cost:** every model call's token usage is recorded, and reports price it with `evals/pricing.yaml` (USD per 1M tokens, uncached input, cached input and output). Add a line there for any new model; a model without a price shows "no price". The prices are list prices from a given date, so re-check them before quoting the numbers.

**Reading the output:** each case prints `PASS` or `FAIL` with its type (`number` or `behavior`), failures add a one-line reason, and the end shows totals for each type. The exit code is 0 if every case passed and 1 otherwise, so it can gate a script. A full run takes about two minutes.

**The cases** are in `evals/cases.yaml`. Each has three fields:

- `query`: the question.
- `exact_match`: `true` if the expected response is a number or name, `false` if it describes a behavior.
- `expected_response`: for `true`, the correct answer. A reply that contains the number at the precision it shows ("$47,904" matches 47903.60) passes without a judge call; otherwise the judge decides, so "$47.9K" or a number written in words can still pass. For `false`, the expected behavior in words (out-of-scope questions, schema questions, guardrail violations, clarifying questions), always graded by the judge.

The runner uses a throwaway copy of the demo database and always turns all guardrails on, so your `.env` guardrail settings do not affect it. Each case runs once and model answers vary, so a single failure is something to look at, not necessarily a regression.

**Adding or changing a case:** for a numeric case, add the question and a reference SQL query to `evals/reference.py`, then run `python -m evals.reference` to print the correct answer and copy it into `expected_response`. Use explicit dates ("March 2026") so the answer does not change over time. `pytest` (no API calls) checks the case file format and that every expected number matches its reference query.
