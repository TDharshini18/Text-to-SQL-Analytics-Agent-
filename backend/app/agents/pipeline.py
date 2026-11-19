"""The agent loop that connects everything, written as a generator of events.

  question
    -> Schema Agent         read tables, columns, keys, example rows, column documentation
    -> Schema Linking Agent pick the relevant tables (names, stored values, LLM, foreign keys)
    -> SQL Agent            write a query from the linked schema
    -> validator + executor safety check, then run it read-only
    -> self-correction, driven by feedback from running the query:
         error          the database / safety-check error goes back to the SQL Agent
         0 rows         sent back once to check its filters
         result review  the Verifier Agent checks the columns and logic against the question
       (up to MAX_ATTEMPTS; a "no such table/column" error widens to the full schema;
        if a revision fails, the last query that ran is kept)
    -> Explanation Agent    answer in plain English

Each step yields an event, so the UI can show the agent's work live (/chat/stream),
and /chat simply runs the generator to the end.
"""

import sqlite3
import time
from collections.abc import Iterator

from app import config
from app.agents.explanation_agent import explain
from app.agents.schema_agent import get_schema, schema_to_text
from app.agents.schema_linking import LinkResult, build_value_index, category_values, link_schema
from app.agents.sql_agent import generate_sql
from app.agents.verifier import review_result
from app.database.descriptions import load_descriptions
from app.services.sql_executor import execute_sql
from app.services.sql_validator import UnsafeSQLError, validate_sql

MAX_ATTEMPTS = 3

EMPTY_RESULT_FEEDBACK = (
    "The query ran but returned 0 rows. Check each filter: is it on the right column, does "
    "the value match how it is stored (see the listed values and example rows), and is every "
    "JOIN needed? If 0 rows really is the correct answer, return the same query unchanged."
)

REVIEW_FEEDBACK = (
    "The query ran, but a review of its result found this problem:\n{problem}\n"
    "Fix it. If you are sure the query was already right, return it unchanged."
)

# Value index per database file, rebuilt when the file changes.
_value_cache: dict[tuple[str, float], list] = {}


def _value_index(conn: sqlite3.Connection, schema: dict) -> list:
    key = (str(config.DB_PATH), config.DB_PATH.stat().st_mtime)
    if key not in _value_cache:
        _value_cache.clear()
        _value_cache[key] = build_value_index(conn, schema)
    return _value_cache[key]


class PipelineError(Exception):
    def __init__(self, message: str, sql: str = ""):
        super().__init__(message)
        self.message = message
        self.sql = sql


def run_pipeline(
    conn: sqlite3.Connection,
    question: str,
    *,
    use_linking: bool = True,
    use_review: bool = True,
    max_attempts: int = MAX_ATTEMPTS,
    explain_results: bool = True,
) -> Iterator[dict]:
    """The options exist for the benchmark (benchmarks/bird_eval.py), to measure each part."""
    started = time.monotonic()

    # 1. Schema (+ documentation and category values, when available)
    yield {"type": "status", "step": "schema", "message": "Reading the database schema"}
    schema = get_schema(conn)
    descriptions = load_descriptions(config.DB_PATH)
    values = _value_index(conn, schema)
    categories = category_values(values)

    # 2. Schema linking
    if use_linking:
        yield {"type": "status", "step": "linking", "message": "Linking the question to tables and columns"}
        link = link_schema(question, schema, values, descriptions)
    else:
        all_tables = [t["name"] for t in schema["tables"]]
        link = LinkResult(all_tables, {}, [], {t: ["linking off"] for t in all_tables}, "off")
    link_info = link.to_dict() | {"total_tables": len(schema["tables"])}
    yield {"type": "linking", **link_info}

    def prompt_schema(tables):
        return schema_to_text(schema, tables, link.to_dict(), descriptions, categories)

    schema_text = prompt_schema(link.tables)
    widened = False

    # 3. Generate -> validate -> execute -> self-correct
    history: list[tuple[str, str]] = []
    attempts: list[dict] = []
    columns: list[str] = []
    rows: list[list] = []
    sql = ""
    reviewed_empty = reviewed_result = False
    last_good: tuple[str, list, list] | None = None  # the last query that ran
    for n in range(1, max_attempts + 1):
        yield {
            "type": "status",
            "step": "generating",
            "message": "Writing SQL" if n == 1 else f"Revising the query (attempt {n} of {max_attempts})",
        }
        sql = generate_sql(question, schema_text, history)
        t0 = time.monotonic()
        try:
            validate_sql(sql)
            columns, rows = execute_sql(conn, sql)
        except (UnsafeSQLError, sqlite3.Error) as e:
            error = f"{type(e).__name__}: {e}" if isinstance(e, sqlite3.Error) else f"Safety check: {e}"
            attempt = {"n": n, "sql": sql, "ok": False, "error": error}
            attempts.append(attempt)
            yield {"type": "attempt", **attempt}
            history.append((sql, f"That query failed when it was run:\n{error}"))

            # The linked schema may have left out what the query needs: widen it once.
            if not widened and len(link.tables) < len(schema["tables"]) and (
                "no such table" in str(e) or "no such column" in str(e)
            ):
                widened = True
                schema_text = prompt_schema(None)
                yield {"type": "widened", "message": "Error referenced a missing table or column: using the full schema"}
            continue

        attempt = {"n": n, "sql": sql, "ok": True, "rows": len(rows), "ms": round((time.monotonic() - t0) * 1000)}
        last_good = (sql, columns, rows)
        unchanged = len(history) > 0 and history[-1][0].strip() == sql.strip()
        can_retry = n < max_attempts and not unchanged

        feedback = None
        if can_retry and not rows and not reviewed_empty:
            # No rows is often a wrong filter (wrong column, value spelled differently).
            reviewed_empty = True
            feedback = EMPTY_RESULT_FEEDBACK
            attempt["note"] = "Returned no rows: sent back to check its filters"
        elif can_retry and rows and use_review and not reviewed_result:
            reviewed_result = True
            yield {"type": "status", "step": "reviewing", "message": "Checking the result against the question"}
            problem = review_result(question, sql, columns, rows)
            if problem:
                feedback = REVIEW_FEEDBACK.replace("{problem}", problem)
                attempt["note"] = f"Result review: {problem}"

        attempts.append(attempt)
        yield {"type": "attempt", **attempt}
        if feedback is None:
            break
        history.append((sql, feedback))
    else:
        if last_good is None:
            raise PipelineError(
                f"Could not build a working query after {max_attempts} attempts. Last error: {history[-1][1]}",
                sql,
            )
        # The last revision failed to run: keep the last query that did.
        sql, columns, rows = last_good

    # 4. Explain
    if explain_results:
        yield {"type": "status", "step": "explaining", "message": "Explaining the results"}
    explanation = explain(question, sql, columns, rows) if explain_results else ""

    yield {
        "type": "result",
        "response": {
            "question": question,
            "sql": sql,
            "columns": columns,
            "results": rows,
            "explanation": explanation,
            "truncated": len(rows) >= config.MAX_ROWS,
            "trace": {
                "linking": link_info,
                "attempts": attempts,
                "widened": widened,
                "total_ms": round((time.monotonic() - started) * 1000),
            },
        },
    }
