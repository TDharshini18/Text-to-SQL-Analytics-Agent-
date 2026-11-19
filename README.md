# Text-to-SQL Analytics Agent

Ask a relational database a question in plain English. An agent pipeline links the question
to the right part of the schema, writes the SQL, runs it read-only, repairs it from the
database's own error messages when it fails, and explains the result. The Angular UI streams
every step live and lets you review, edit and re-run the SQL next to its results.

```
Angular UI ──POST /chat/stream (NDJSON, one event per step)──> FastAPI   agents/pipeline.py
                                                                  │
   1. Schema Agent          reads tables, columns, types, foreign keys, example rows
   2. Schema Linking Agent  picks the relevant tables/columns:
                              - names in the question     ("cities"  -> customers.city)
                              - values stored in the DB   ("Kochi"   -> customers.city = 'Kochi')
                              - LLM linking for meaning   ("revenue" -> orders.amount)
                              - foreign-key closure adds the bridge tables needed for joins
   3. SQL Agent             LLM (Groq) writes a SQLite SELECT from the linked schema
      SQL validator         plain Python: one SELECT only, no writes
      SQL executor          read-only database, 10 s limit, 500 rows max
        └─ on failure: self-correction loop. The failed SQL and the exact database error
           go back to the SQL Agent as a conversation, up to 3 attempts. A "no such
           table/column" error widens the prompt from the linked schema to the full one.
   4. Explanation Agent     LLM answers the question in plain English from the results
```

## Run it (Windows, PowerShell)

You need Python 3.10+ and Node 20+.

### 1. Backend (terminal 1)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `backend\.env` and paste your Groq key after `GROQ_API_KEY=`. Then:

```powershell
python create_sample_db.py          # only needed if data\sample.sqlite is missing
uvicorn app.main:app --reload
```

The API runs on http://localhost:8000 (interactive docs at http://localhost:8000/docs).

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 2. Frontend (terminal 2)

```powershell
cd frontend
npm install
npm start
```

Open http://localhost:4200 and ask, for example:

- Show me the top 5 customers by total revenue
- Which city has the most orders?
- Total revenue from customers in Kochi by product category
- Monthly revenue for 2025

### Tests

```powershell
cd backend
python -m pytest
```

The tests cover schema linking (names, stored values, foreign-key bridge tables, names the
LLM invents), the self-correction loop (repair from an execution error, from the safety
check, widening the schema, giving up after 3 attempts) and the validator. The LLM is faked,
so they run offline.

## Using the UI

- The sidebar lists the tables. Click a column name to add it to your question. Tables used
  by the latest answer are marked LINKED.
- Each answer shows the agent steps (linked tables, matched values, every SQL attempt and the
  error that triggered a repair), the explanation, the SQL and the results together.
- **Edit** on the SQL lets you change the query and run it again (Ctrl+Enter). It goes through
  the same safety check and read-only connection. **Reset** goes back to the original.
- Click a column header to sort. **Copy CSV** / **Download** to export.
- Keys: Enter sends, Shift+Enter adds a line, Up recalls the last question, / focuses the box.
- Light and dark themes follow the operating system setting.

## Use your own database

Set `DB_PATH` in `backend\.env` to any SQLite file and restart the backend, for example:

```
DB_PATH=C:\path\to\california_schools.sqlite
```

## Change the model

Set `GROQ_MODEL` in `backend\.env` to any chat model listed at https://console.groq.com/docs/models.

## Project layout

```
backend/app/
  main.py                        FastAPI app + CORS for the Angular dev server
  config.py                      reads backend/.env
  api/chat.py                    the endpoints
  agents/pipeline.py             the agent loop: link, generate, validate, run, repair, explain
  agents/schema_agent.py         schema -> prompt text (whole, or only the linked tables)
  agents/schema_linking.py       schema linking: names, stored values, LLM, foreign-key closure
  agents/sql_agent.py            question (+ earlier failed attempts and their errors) -> SQL
  agents/explanation_agent.py    results -> plain-English answer
  database/connection.py         opens SQLite read-only
  database/schema.py             reads tables, columns, foreign keys, example rows
  services/llm.py                calls the Groq API
  services/sql_validator.py      safety check (not AI)
  services/sql_executor.py       runs the query with a time and row limit
  models/request.py              request/response shapes
backend/tests/test_agents.py     tests (offline, fake LLM)
backend/create_sample_db.py      builds the sample shop database

frontend/src/app/
  pages/chat/                    the page: sidebar + conversation, consumes the event stream
  components/agent-trace/        live agent steps: linking, SQL attempts and repairs
  components/sql-display/        highlighted SQL, copy, edit and re-run
  components/results-table/      sortable results, single-value view, CSV export
  components/schema-panel/       tables and columns, linked tables marked
  components/chat-input/         question box
  services/sql-ai.service.ts     HTTP + streaming client
  format.ts                      SQL highlighting, number formatting, small Markdown, CSV
```

## API

| Endpoint | What it does |
|---|---|
| `GET /schema` | tables, columns, keys, example rows |
| `POST /chat` `{"question": "..."}` | runs the pipeline, returns the answer |
| `POST /chat/stream` `{"question": "..."}` | the same, streamed as one JSON event per line |
| `POST /run-sql` `{"sql": "..."}` | runs user-edited SQL (validated, read-only, no LLM) |

`POST /chat` returns:

```json
{
  "question": "Total revenue from customers in Kochi by product category",
  "sql": "SELECT p.category, SUM(o.amount) AS total_revenue FROM ...",
  "columns": ["category", "total_revenue"],
  "results": [["Electronics", 537500.0], ["Furniture", 158400.0]],
  "explanation": "Customers in Kochi generated ...",
  "truncated": false,
  "trace": {
    "linking": {
      "tables": ["customers", "orders", "products"],
      "values": [{"table": "customers", "column": "city", "value": "Kochi"}],
      "method": "lexical+value+llm",
      "total_tables": 3
    },
    "attempts": [{"n": 1, "sql": "...", "ok": true, "rows": 4, "ms": 2}],
    "widened": false,
    "total_ms": 2700
  }
}
```

A failed attempt looks like `{"n": 1, "sql": "...", "ok": false, "error": "OperationalError: no such column: amout"}`.

Stream events: `status` (a step started), `linking`, `attempt` (one per SQL attempt),
`widened`, then `result` or `error`.

Errors on `/chat`: `422` if there is no working query after 3 attempts (includes the last SQL
tried), `502` if the Groq call failed, `500` if the database file is missing.

## Safety

The model's SQL (and SQL edited in the UI) is never trusted. Two independent locks:

1. **Validator** (`sql_validator.py`): one statement only, must start with `SELECT` or `WITH`,
   and whole-word checks block `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`,
   `ATTACH`, `PRAGMA` and similar. (Whole-word, so a column named `created_at` is fine.)
2. **Read-only database** (`connection.py`): opened with `mode=ro` and `PRAGMA query_only`,
   so even a query that got past the validator could not change anything.

Queries are also stopped after 10 seconds, and at most 500 rows are returned.
