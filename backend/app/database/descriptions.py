"""Optional column documentation, so the agents know what cryptic columns mean.

If a folder named `database_description` sits next to the database file, it is read:
one CSV per table (file name = table name) with the columns

  original_column_name, column_name, column_description, data_format, value_description

(the format the BIRD benchmark ships, and an easy one to write for your own database).
Example: SOC -> "School ownership code" with a list of what each code means.
"""

import csv
import io
import re
from functools import lru_cache
from pathlib import Path

MAX_DESCRIPTION = 160   # characters kept per description, to keep prompts small
MAX_VALUES_NOTE = 240


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(text: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("·", "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@lru_cache(maxsize=32)
def load_descriptions(db_path: Path) -> dict[str, dict[str, dict]]:
    """{table (lower case): {column (lower case): {"name", "description", "values"}}}"""
    folder = Path(db_path).parent / "database_description"
    if not folder.is_dir():
        return {}
    result: dict[str, dict[str, dict]] = {}
    for csv_file in folder.glob("*.csv"):
        columns: dict[str, dict] = {}
        for row in csv.DictReader(io.StringIO(_read_text(csv_file))):
            row = {(k or "").strip().lower(): v for k, v in row.items()}
            original = (row.get("original_column_name") or "").strip()
            if not original:
                continue
            name = _clean(row.get("column_name"), 80)
            description = _clean(row.get("column_description"), MAX_DESCRIPTION)
            values = _clean(row.get("value_description"), MAX_VALUES_NOTE)
            # Drop text that only repeats the column name.
            if name.lower() == original.lower():
                name = ""
            if description.lower() in (original.lower(), name.lower()):
                description = ""
            if name or description or values:
                columns[original.lower()] = {"name": name, "description": description, "values": values}
        if columns:
            result[csv_file.stem.lower()] = columns
    return result


def describe_column(descriptions: dict, table: str, column: str, include_values: bool = True) -> str:
    """One line of documentation for a column, or "" if there is none."""
    info = descriptions.get(table.lower(), {}).get(column.lower())
    if not info:
        return ""
    parts = [p for p in (info["name"], info["description"]) if p]
    if include_values and info["values"]:
        parts.append(f"values: {info['values']}")
    return "; ".join(parts)
