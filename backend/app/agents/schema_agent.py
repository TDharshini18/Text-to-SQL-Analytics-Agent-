"""Schema Agent: reads the database structure and writes it as prompt text.

No LLM call is needed: the database already describes itself. When available it adds
column documentation (database/descriptions.py) and, for category-like text columns,
the actual values stored, so the SQL agent filters on real values instead of guessing.
"""

import sqlite3

from app.database.descriptions import describe_column
from app.database.schema import read_schema


def get_schema(conn: sqlite3.Connection) -> dict:
    return read_schema(conn)


def schema_to_text(
    schema: dict,
    tables: list[str] | None = None,
    link: dict | None = None,
    descriptions: dict | None = None,
    categories: dict[tuple[str, str], list[str]] | None = None,
) -> str:
    """Schema as prompt text, optionally only the linked `tables`, plus linking hints.

    Example output:

    TABLE "schools"
      CDSCode TEXT PRIMARY KEY
      SOC TEXT -- School ownership code; values: 62: Elementary School ...
      County TEXT -- County name
      FundingType TEXT -- one of: 'Directly funded', 'Locally funded', 'Not in CS funding model'
      example row: ['01100170000000', 'Alameda', ...]
      schools.CDSCode -> frpm.CDSCode
    """
    descriptions = descriptions or {}
    categories = categories or {}
    lines = []
    for table in schema["tables"]:
        if tables is not None and table["name"] not in tables:
            continue
        lines.append(f'TABLE "{table["name"]}"')
        for c in table["columns"]:
            line = f"  {_quote(c['name'])} {c['type']}{' PRIMARY KEY' if c['primary_key'] else ''}"
            notes = []
            doc = describe_column(descriptions, table["name"], c["name"])
            if doc:
                notes.append(doc)
            values = categories.get((table["name"], c["name"]))
            if values:
                notes.append("one of: " + ", ".join(f"'{v}'" for v in values))
            if notes:
                line += " -- " + " | ".join(notes)
            lines.append(line)
        for fk in table["foreign_keys"]:
            lines.append(f"  {table['name']}.{fk['column']} -> {fk['references']}")
        for row in table["sample_rows"][:2]:
            lines.append(f"  example row: {row}")
        lines.append("")

    if link:
        relevant = [f"{t}.{c}" for t, cols in link.get("columns", {}).items() for c in cols]
        if relevant:
            lines.append("Columns most likely needed: " + ", ".join(relevant))
        for v in link.get("values", []):
            how = "is stored" if v.get("match", "exact") == "exact" else "is probably stored as"
            lines.append(
                f"The question mentions '{v.get('mention', v['value'])}', which {how} "
                f"'{v['value']}' in {v['table']}.{v['column']} (use this exact spelling)."
            )
    return "\n".join(lines).strip()


def _quote(name: str) -> str:
    return f'"{name}"' if not name.replace("_", "").isalnum() else name
