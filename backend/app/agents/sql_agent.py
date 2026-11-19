"""SQL Generation Agent: turns a plain-English question into a SQLite query.

On a repair attempt it sees the whole history as a conversation: each query it wrote
and the exact error the database (or the safety check) gave back.
"""

import re

from app.services.llm import chat_llm

SYSTEM_PROMPT = """You are an expert SQLite analyst.
Write ONE SQLite SELECT query that answers the user's question.

Rules:
- Use only the tables and columns in the schema below, with their exact names.
- Put double quotes around table or column names that contain spaces.
- The SQL dialect is SQLite (dates are text: use strftime / date functions).
- Never modify data: no INSERT, UPDATE, DELETE, DROP, ALTER or CREATE.
- If the question comes with a Hint, follow it exactly: it defines the formulas, columns and
  values to use. A hint that explains a term is a definition that tells you which column to
  use, not an extra filter: "grades 1-12 means K-12" means use the (K-12) columns, not
  WHERE grades = 'K-12'.
- Select exactly what the question asks for, in the order it asks:
  - no helper columns: do not add the value you sorted or filtered by, an ID, a name or a
    rank unless the question asks to show it;
  - answers made of parts (full name, address) are returned one part per column; never
    join columns together with ||.
- SQLite sorts NULL first in ascending order. For "lowest / smallest / bottom N" with
  ORDER BY ... ASC LIMIT, add `<column> IS NOT NULL`. Do not add IS NOT NULL elsewhere
  unless the question asks for it.
- Join only the tables the answer needs.
- Use CAST(x AS REAL) when dividing, so integer division does not truncate.
- Give result columns clear names with AS.
- Reply with only the SQL inside a ```sql code block. No explanation.

Database schema:
{schema}"""

OUTPUT_REMINDER = (
    "(Select only what the question asks to see. No extra columns: not the value used for "
    "sorting or filtering, not a name or ID next to a requested number.)"
)

REPAIR_PROMPT = """{feedback}

Find the cause, then reply with the query in a ```sql code block. No explanation."""


def extract_sql(reply: str) -> str:
    """The model usually wraps SQL in ```sql ... ```; take what is inside, or the whole reply."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", reply, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else reply
    return sql.strip().rstrip(";").strip()


def generate_sql(
    question: str,
    schema_text: str,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """history: earlier (sql, feedback) pairs from this question, oldest first. Feedback is a
    database error, a note that it returned no rows, or a problem found by the result review."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.replace("{schema}", schema_text)},
        # The column rule is repeated next to the question: far up in a long prompt it is often missed.
        {"role": "user", "content": f"{question}\n\n{OUTPUT_REMINDER}"},
    ]
    for sql, feedback in history or []:
        messages.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
        messages.append({"role": "user", "content": REPAIR_PROMPT.replace("{feedback}", feedback)})
    return extract_sql(chat_llm(messages))
