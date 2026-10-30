# Analytics Agent — Design Document

A text-to-SQL web app. A user asks a question in plain language. The agent asks clarifying questions if it needs to, writes SQL, runs it against the database and shows the results. The conversation is multi-turn.

- **Language:** Python only (3.11+)
- **Frontend:** Streamlit
- **LLM provider:** Kimi (Moonshot AI), through its OpenAI-compatible API
- **Schema and business context:** YAML files kept in the repo (the app does not introspect the database at runtime)
- **One domain at a time, domain-agnostic code:** the app serves a single domain (e-commerce for the demo). All domain knowledge lives in the YAML files, so replacing them and pointing to another database turns the same code into a different app, such as a student registry. See Section 2.
- **Simple:** a small, flat, readable codebase. See Section 3.

---

## 1. Goals and Non-Goals

### Goals
1. Answer analytics questions in natural language by generating and running SQL.
2. Ground the SQL in curated metadata: a **data catalog** (one YAML per table), a **knowledge** file (business context) and **example** question/SQL pairs.
3. Ask a **clarifying question** when the request is ambiguous, instead of guessing.
4. Support **multi-turn conversation**, so follow-ups like "now break that down by month" work.
5. Be **safe by default**: read-only queries, row limits, timeouts.
6. Keep the **code domain-agnostic**: the app runs one domain at a time, and moving to a new domain means replacing the YAML and the database URL, not editing code.
7. Keep the **code simple**: clean, readable Python that someone can understand in one sitting.

### Non-Goals (v1)
- Charts beyond Streamlit's built-in ones
- User authentication or multi-tenant access control
- Writing to the database (INSERT/UPDATE/DELETE/DDL)
- Generating the YAML catalog from the database automatically
- Vector databases, embeddings, or LLM frameworks (LangChain, LlamaIndex, etc.)
- Supporting several LLM providers at once
- Several domains in one app or one repo: no domain switcher, no folder of multiple domains, no multi-domain tests

---

## 2. Core Principle: One Domain, Domain-Agnostic Code

The app is built for **one domain at a time**. The demo uses an e-commerce database. There is exactly one set of YAML files in the repo, in a `semantic_layer/` folder, and one database. Nothing in the design plans for several domains living side by side.

What makes it reusable is that **the Python code knows nothing about the domain.** To use it for something else, such as a student registry, you replace the contents of `semantic_layer/`, point `DATABASE_URL` at the new database, and run it. No code changes.

### 2.1 The semantic layer folder

```
semantic_layer/
├── data_catalog/
│   ├── orders.yaml
│   ├── customers.yaml
│   └── products.yaml
├── knowledge.yaml
└── examples.yaml
```

### 2.2 Rules for the implementer

1. **No domain words in code.** No table names, metric names, business terms or domain example questions in any `.py` file, prompt or UI string. Words like "order", "customer" or "revenue" appear only inside `semantic_layer/`.
2. **Prompts are generic templates.** The prompt describes the role and the rules for using the catalog. All business meaning is filled in from the YAML at runtime.
3. **The UI is branded from YAML.** The app title, subtitle and starter questions come from the `app` section of `knowledge.yaml` (Section 6.2), with generic fallbacks ("Analytics Agent", "Ask a question about your data").
4. **Behavior comes from YAML fields, not names.** Table selection, PII hiding and clarifying questions depend only on YAML fields (`tags`, `relationships`, `pii`, `ambiguities`), never on specific table or column names.
5. **The YAML format is the contract.** Moving to a new domain means writing YAML that follows Section 6, never editing Python.

### 2.3 How this is checked

- **Domain-word test:** `tests/test_no_domain_terms.py` reads the table names, metric names and glossary terms from `semantic_layer/`, and fails if any of them appears as a whole word in a `.py` file. Column names are left out, since many are generic (`id`, `name`, `status`). A short allowlist inside the test covers legitimately generic words.
- **Generic test fixtures:** unit tests use neutral names (`table_a`, `col_x`), so they keep passing after the semantic layer is replaced.

---

## 3. Code Principles: Keep It Simple

This is a demo that people will read. Readability beats cleverness and flexibility.

### 3.1 Style
- **Python 3.11+, type hints on every function signature.** Format and lint with `ruff`.
- **Plain functions first.** Use a class only when something holds state (e.g. the conversation). Use `@dataclass` for simple records and Pydantic only for validating the YAML.
- **Small, well-named functions.** A function does one thing and fits on a screen. Names say what it does (`build_system_prompt`, `validate_sql`), so comments are rarely needed.
- **Comments explain *why*, not *what*.** A one-line docstring on each public function. No boilerplate docstrings.
- **Fail fast, with clear messages.** Bad YAML or config stops the app at startup, naming the file and field. No bare `except:`; catch specific errors only where something useful can be done (e.g. passing a DB error back to the model).
- **No magic.** No metaclasses, decorators that hide control flow, dynamic imports, or global mutable state outside `st.session_state`.

### 3.2 Modularize when needed, not before
- **One file per concern, in a flat package.** About eight Python files total (Section 5). No sub-packages.
- **Split a file only when it has two unrelated jobs or grows past ~300 lines.** Don't create a module for a single 10-line function.
- **No speculative abstraction.** No base classes, interfaces, registries, plugin systems, factories or dependency injection. There is one LLM provider and one database connection, so call them directly. If a second one is ever needed, refactor then.
- **No frameworks on top of the essentials.** The agent loop is a plain `for` loop over OpenAI-style tool calls, not LangChain or an agent framework.
- **Few dependencies** (Section 12). Prefer the standard library when it's just as clear.

### 3.3 Size budget
Aim for **under ~1,000 lines of Python** (excluding tests and YAML). If the code goes well beyond that, simplify before adding more.

---

## 4. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Streamlit UI (app.py)                    │
│        chat · SQL viewer · results table · sidebar           │
└───────────────┬──────────────────────────────────────────────┘
                │ user message + conversation
                ▼
┌──────────────────────────────────────────────────────────────┐
│                        agent.py                              │
│  build prompt → call Kimi with tools →                       │
│  clarify  OR  validate SQL → run → answer                    │
│  (on SQL error, send the error back and retry, max N steps)  │
└───────┬─────────────────┬───────────────────┬────────────────┘
        ▼                 ▼                   ▼
   metadata.py         llm.py               db.py
   prompts.py      (OpenAI SDK →       (sqlglot guard +
  (YAML → prompt)      Kimi)             SQLAlchemy)
        ▼                                     ▼
   semantic_layer/*.yaml                   Database
```

---

## 5. Project Layout

```
analytics-agent/
├── analytics_agent/
│   ├── app.py          # Streamlit UI: chat, results, sidebar
│   ├── agent.py        # the agent loop, tool definitions, Conversation dataclass
│   ├── prompts.py      # system prompt template + rendering catalog/knowledge/examples to text
│   ├── metadata.py     # Pydantic models for the YAML, load_metadata(), pick_tables()
│   ├── llm.py          # Kimi client (OpenAI SDK with Moonshot base_url)
│   ├── db.py           # engine, validate_sql() guard, run_query()
│   ├── config.py       # settings read from environment / .env
├── demo/
│   ├── seed.sql        # demo only: builds the demo database
│   └── seed_db.py      # demo only: runs demo/seed.sql against DATABASE_URL
├── semantic_layer/     # ← ALL domain-specific content (Section 2)
├── data/               # generated demo database (git-ignored)
├── tests/
│   ├── test_metadata.py
│   ├── test_db.py              # guard: blocks writes, adds LIMIT
│   ├── test_agent.py           # LLM mocked
│   └── test_no_domain_terms.py
├── .env.example
├── requirements.txt
└── README.md           # setup, run, and "how to use this for another domain"
```

Run with:

```bash
python -m demo.seed_db
streamlit run analytics_agent/app.py
```

---

## 6. YAML Metadata Specification

All three types are loaded at startup from `SEMANTIC_LAYER_PATH`, validated with Pydantic and cached with `st.cache_resource`. If a file is invalid, the app stops with a clear error naming the file and field. At startup, the loader also checks that every catalog table exists in the database and shows a warning in the sidebar for any that don't.

> The examples below are from the e-commerce demo and only illustrate the format. The code must not depend on any of these names.

### 6.1 Data Catalog: `data_catalog/<table>.yaml` (one file per table)

```yaml
table: orders
description: >
  One row per customer order. Cancelled orders are kept, with status = 'cancelled'.
grain: one row per order_id
primary_key: [order_id]
tags: [sales, revenue]          # optional; used for table selection

columns:
  - name: order_id
    type: INTEGER
    description: Unique order identifier.
  - name: customer_id
    type: INTEGER
    description: The customer who placed the order.
    foreign_key: customers.customer_id
  - name: order_date
    type: DATE
    description: Date the order was placed (UTC).
  - name: status
    type: VARCHAR
    description: Order lifecycle status.
    allowed_values: [pending, shipped, delivered, cancelled, refunded]
  - name: total_amount
    type: DECIMAL(12,2)
    description: Order total in USD, including tax, excluding shipping.

relationships:
  - to_table: customers
    on: orders.customer_id = customers.customer_id
```

**Required fields:** `table`, `description`, `columns[].name`, `columns[].type`.
**Optional fields:** everything else. Columns marked `pii: true` are left out of the prompt, so the model never sees or selects them.

### 6.2 Knowledge: `knowledge.yaml`

Business context that applies across tables: app branding, metric definitions, glossary terms, rules and ambiguous terms.

```yaml
app:                           # optional; drives the UI so the code has no domain text
  title: Acme Sales Analytics
  subtitle: Ask questions about orders, customers and products.
  starter_questions:           # shown as clickable buttons on an empty chat
    - What was revenue last month?
    - Who are our top 10 customers by AOV?

business_overview: >
  Acme is a B2C e-commerce company selling home goods in the US and Canada.

metrics:
  - name: revenue
    definition: Sum of orders.total_amount for orders not cancelled or refunded.
    sql: SUM(CASE WHEN status NOT IN ('cancelled','refunded') THEN total_amount END)

glossary:
  - term: AOV
    meaning: Average order value = revenue / number of non-cancelled orders.

rules:
  - Weeks start on Monday.
  - '"Last month" means the previous full calendar month, not the last 30 days.'
  - Always exclude test accounts (customers.is_test = true).

ambiguities:                   # terms that should trigger a clarifying question
  - term: sales
    note: Could mean revenue (USD) or number of orders.
```

### 6.3 Examples: `examples.yaml`

Question → SQL pairs that show the model house style and known-good patterns.

```yaml
examples:
  - question: What was monthly revenue in 2025?
    sql: |
      SELECT DATE_TRUNC('month', order_date) AS month,
             SUM(total_amount) AS revenue
      FROM orders
      WHERE status NOT IN ('cancelled','refunded')
        AND order_date >= '2025-01-01' AND order_date < '2026-01-01'
      GROUP BY 1
      ORDER BY 1;
```

---

## 7. Building the Prompt

`prompts.py` turns the YAML into prompt text. Keep it simple:

1. **Tables:** if the catalog has **≤ 20 tables, include all of them** (the common demo case). Above that, `metadata.pick_tables()` keeps the tables whose name, description, tags or column names share words with the recent conversation, plus their direct `relationships`. That is plain word overlap, nothing more.
2. **Knowledge:** include all of it. It is short by design.
3. **Examples:** include up to 5 examples, ranked by word overlap with the question.

Tables render as compact text, for example:

```
### orders  (one row per order_id)
One row per customer order...
- order_id INTEGER PK — Unique order identifier.
- customer_id INTEGER → customers.customer_id — ...
- status VARCHAR [pending|shipped|delivered|cancelled|refunded] — ...
```

### System prompt template

```
You are Analytics Agent, an expert data analyst who writes {dialect} SQL.
You answer questions about this business: {business_overview}

## Rules
- Use only tables and columns listed in the Data Catalog. Never invent columns.
- Follow the business rules and metric definitions in Knowledge exactly.
- Write a single read-only SELECT query (CTEs are allowed).
- If the question is ambiguous in a way that changes the result, call ask_clarification.
  Ask at most one question, and offer options when you can.
- If a reasonable default exists, use it and state the assumption instead of asking.
- Otherwise call run_sql. After you see the results, call final_answer with a short
  summary of the key numbers and any assumptions.
- For follow-ups, keep the filters and definitions from earlier turns unless the user changes them.
- Today's date is {today}.

## Data Catalog
{catalog}

## Knowledge
{knowledge}

## Examples
{examples}
```

---

## 8. Agent Design (`agent.py`)

### 8.1 Tools

Kimi supports OpenAI-style function calling. The agent defines three tools as plain dicts:

| Tool | Purpose | Arguments |
|---|---|---|
| `ask_clarification` | Ask the user a question before writing SQL | `question: str`, `options: list[str]` (optional, shown as buttons) |
| `run_sql` | Run a read-only query | `sql: str` |
| `final_answer` | Reply to the user (after results, or when no SQL is needed) | `answer: str` |

### 8.2 The loop

One function, `answer(conversation, user_message) -> Reply`, roughly:

```python
def answer(conversation: Conversation, user_message: str) -> Reply:
    conversation.add_user(user_message)
    messages = [system_prompt(metadata, conversation)] + conversation.recent_messages()
    last_result = None

    for _ in range(settings.max_agent_steps):  # default 5
        call = llm.chat(messages, TOOLS)  # one tool call per step
        if call is None:  # model replied with plain text
            return conversation.reply(text=..., result=last_result)
        if call.name == "ask_clarification":
            return conversation.reply(question=..., options=...)
        if call.name == "final_answer":
            return conversation.reply(text=..., result=last_result)
        if call.name == "run_sql":
            try:
                sql = db.validate_sql(call.args["sql"])  # raises on unsafe SQL; adds LIMIT
                last_result = db.run_query(sql)
                tool_output = preview(last_result)  # columns, row count, first 20 rows
            except (db.UnsafeSQLError, db.QueryError) as e:
                tool_output = f"Error: {e}"  # the model fixes it on the next step
            messages += tool_messages(call, tool_output)

    return conversation.reply(
        text="Sorry, I couldn't answer that. Try rephrasing.", result=last_result
    )
```

`Reply` is a small dataclass: `text`, `question`, `options`, `sql`, `dataframe`, `error`.

### 8.3 Multi-turn memory

- A `Conversation` dataclass lives in `st.session_state`. It holds the OpenAI-format messages (including tool calls and results) so the model sees earlier SQL.
- `recent_messages()` returns the last 10 turns. Tool results in older turns keep only the column names and row count, so the prompt stays small.
- "New conversation" in the sidebar replaces it with a fresh one.

---

## 9. LLM Integration: Kimi (`llm.py`)

Kimi exposes an **OpenAI-compatible** Chat Completions API, so use the official `openai` SDK with a custom `base_url`. The SDK already retries on 429/5xx, so no extra retry library is needed.

```python
from openai import OpenAI
from analytics_agent.config import settings

client = OpenAI(
    api_key=settings.moonshot_api_key,
    base_url=settings.moonshot_base_url,
    max_retries=3,
    timeout=60,
)


def chat(messages: list[dict], tools: list[dict]) -> ToolCall | None:
    """Call Kimi and return its first tool call, or None if it replied with text."""
    response = client.chat.completions.create(
        model=settings.kimi_model,
        messages=messages,
        tools=tools,
        temperature=0.2,
    )
    ...
```

**`.env`:**

```bash
MOONSHOT_API_KEY=sk-...
MOONSHOT_BASE_URL=https://api.moonshot.ai/v1     # use https://api.moonshot.cn/v1 for the China region
KIMI_MODEL=<kimi model id>                       # check the Moonshot docs for current model ids
```

Check the current model ids and tool-calling support in the Moonshot platform docs. Read the model id from config; don't hard-code it.

---

## 10. Database (`db.py`)

- **Engine:** one SQLAlchemy engine from `DATABASE_URL`, created once and cached. The demo uses **SQLite** (no server needed). Any SQLAlchemy URL works if the driver is installed.
- **Dialect:** taken from the engine (`engine.dialect.name`) and passed to the prompt and to `sqlglot`.
- **Read-only user:** for a real database, connect with a read-only user. This is the main safety control; the guard below is a second layer.

**`validate_sql(sql) -> str`** (using `sqlglot`):
1. Parse with the dialect. On a parse error, raise `UnsafeSQLError` with the message.
2. Allow exactly one statement, and it must be a `SELECT` (including `WITH` and `UNION`).
3. Reject any write or DDL node anywhere in the tree (`INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, …).
4. If there is no `LIMIT`, add `LIMIT {MAX_ROWS}` (default 1000).

**`run_query(sql) -> pd.DataFrame`:** runs with a timeout (`QUERY_TIMEOUT_SECONDS`, default 30) and raises `QueryError` with the database's message on failure.

---

## 11. Streamlit UI (`app.py`)

**Header:** title and subtitle from `knowledge.app` (fallbacks: "Analytics Agent" / "Ask a question about your data"). An empty chat shows the starter questions as buttons, or the first few example questions if there are none.

**Chat:** `st.chat_message` / `st.chat_input`. Each assistant reply shows:
- The answer text
- For a clarifying question: the question plus option buttons; clicking one sends it as the next message
- `st.expander("SQL")` with `st.code(sql, language="sql")`
- The results in `st.dataframe`, with row count, and a **Download CSV** button
- A `st.spinner` while the agent works

**Sidebar:** the database, the catalog (tables → columns and descriptions), any startup warnings, and a "New conversation" button.

That's all for v1. Possible later additions: a quick chart, a "run edited SQL" box.

---

## 12. Configuration and Dependencies

`config.py` reads the environment (and `.env` through `python-dotenv`) into one frozen dataclass, `settings`. Missing required values stop the app with a clear message.

| Setting | Default | Description |
|---|---|---|
| `MOONSHOT_API_KEY` | — | Required |
| `MOONSHOT_BASE_URL` | `https://api.moonshot.ai/v1` | Kimi endpoint |
| `KIMI_MODEL` | — | Required |
| `SEMANTIC_LAYER_PATH` | `./semantic_layer` | Folder with the YAML files |
| `DATABASE_URL` | `sqlite:///data/demo.db` | SQLAlchemy URL |
| `MAX_ROWS` | 1000 | LIMIT that gets added |
| `QUERY_TIMEOUT_SECONDS` | 30 | Query timeout |
| `MAX_AGENT_STEPS` | 5 | Tool-call steps per user message |

**`requirements.txt`:**

```
streamlit
openai
pydantic
pyyaml
python-dotenv
sqlalchemy
sqlglot
pandas
pytest
ruff
```

---

## 13. Error Handling

| Failure | Behavior |
|---|---|
| Invalid YAML or missing config | Stop at startup with a clear message (file + field) |
| Catalog table missing from database | Warning in the sidebar; the app still runs |
| Kimi API error after SDK retries | Show a friendly error; the conversation is kept |
| Model replies with text, not a tool call | Treat it as the final answer |
| SQL rejected by the guard, or DB error | Send the error back to the model to fix (counts toward `MAX_AGENT_STEPS`) |
| Max steps reached | Show the last SQL and error and suggest rephrasing |

---

## 14. Testing

Keep tests few and focused:
- **`test_metadata.py`:** the YAML in `semantic_layer/` loads and validates; a broken YAML gives a clear error.
- **`test_db.py`:** the guard blocks writes, DDL and multiple statements, and adds `LIMIT`. Uses an in-memory SQLite database with neutral names (`table_a`, `col_x`).
- **`test_agent.py`:** `llm.chat` is mocked with scripted tool calls. Covers clarify, SQL error → retry → success, and the max-steps cutoff.
- **`test_no_domain_terms.py`:** described in Section 2.3.

---

## 15. Milestones

1. **Skeleton:** layout, `config.py`, the e-commerce semantic layer (YAML), `demo/seed.sql` and `demo/seed_db.py`, `metadata.py` loading and validation.
2. **First answer:** `prompts.py`, `llm.py`, `db.py`, and an `agent.py` that handles `run_sql` + `final_answer`; a basic chat that shows SQL and results.
3. **Clarify and self-correct:** `ask_clarification` with option buttons; errors sent back to the model.
4. **Multi-turn:** `Conversation` in session state, follow-ups work.
5. **Polish and tests:** sidebar catalog, CSV download, starter questions, the four test files, README (including how to swap in another domain).

**Definition of done for every milestone:** the demo works end to end, the tests pass, `ruff` is clean, and the code still follows Section 3.

---

## 16. Open Questions

1. Which database will the demo use besides SQLite, if any (Postgres, Snowflake, BigQuery…)? This only affects the driver in `requirements.txt`.
2. Should conversations be saved between sessions, or is in-memory enough for the demo? (v1 assumes in-memory.)
