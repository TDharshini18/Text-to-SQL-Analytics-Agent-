"""SQL safety check. Plain Python, not AI: the AI's output is never trusted.

This is the first lock. The second is that the database is opened read-only
(see database/connection.py), so even a query that slips past this check cannot write.
"""

import re

FORBIDDEN = [
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "attach", "detach", "pragma", "vacuum", "reindex",
]


class UnsafeSQLError(ValueError):
    pass


# Quoted text: 'string literals', "identifiers", `identifiers` and [identifiers].
QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]")


def validate_sql(sql: str) -> None:
    query = sql.strip().rstrip(";").strip()
    # Check only the SQL itself, not text inside quotes: WHERE note = 'update; drop' is fine.
    code = QUOTED.sub("''", query).lower()

    if not query:
        raise UnsafeSQLError("The query is empty.")
    if ";" in code:
        raise UnsafeSQLError("Only one SQL statement is allowed.")
    if not (code.startswith("select") or code.startswith("with")):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    for word in FORBIDDEN:
        # \b = whole word only, so a column like "created_at" or "updated_on" is still allowed.
        # REPLACE(x, a, b) is a harmless string function; only the REPLACE statement is blocked.
        pattern = rf"\b{word}\b(?!\s*\()" if word == "replace" else rf"\b{word}\b"
        if re.search(pattern, code):
            raise UnsafeSQLError(f"Unsafe SQL: '{word.upper()}' is not allowed.")
