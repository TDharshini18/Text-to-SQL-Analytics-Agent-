"""Result Verifier Agent: checks that a query which ran also answers the question.

The self-correction loop already reacts to errors and empty results. Most wrong answers,
though, run fine: an extra column, a missing filter, a hint not followed. This agent sees
the question, the SQL and the first rows of the result, and either approves it or names
the problem, which goes back to the SQL agent as feedback.
"""

import json
import re

from app.services.llm import LLMError, ask_llm

PROMPT = """You review the result of a SQL query written to answer a question.
Approve it unless there is a clear, specific problem. Check only:
1. Columns: the result has exactly the values the question asks to see, in that order.
   Extra columns (a sort value, a name or ID that was not asked for) or missing ones are problems.
2. Hint: if the question has a Hint, the query uses its formula, columns and values.
3. Logic: filters, joins, grouping and ordering match the question (for example "per
   county" needs grouping; "top 5" needs ORDER BY ... LIMIT 5).
Do not ask for cosmetic changes (column aliases, formatting, rounding).

Reply with JSON only:
{"ok": true}
or
{"ok": false, "problem": "<one or two sentences: what is wrong and how to fix it>"}"""

MAX_ROWS_SHOWN = 8


def review_result(question: str, sql: str, columns: list[str], rows: list[list]) -> str | None:
    """Return a description of the problem, or None if the result looks right."""
    preview = "\n".join(str(tuple(r)) for r in rows[:MAX_ROWS_SHOWN])
    user = (
        f"Question: {question}\n\nSQL:\n{sql}\n\n"
        f"Result columns: {columns}\nRows ({len(rows)} in total, first {min(len(rows), MAX_ROWS_SHOWN)}):\n{preview}"
    )
    try:
        reply = ask_llm(PROMPT, user, json_mode=True)
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        data = json.loads(match.group(0) if match else reply)
    except (LLMError, ValueError):
        return None  # a failed review never blocks an answer
    if data.get("ok", True) is not False:
        return None
    problem = str(data.get("problem") or "").strip()
    return problem or None
