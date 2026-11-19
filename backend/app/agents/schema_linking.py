"""Schema Linking Agent: finds the part of the schema a question is about.

Real databases have many tables; sending all of them to the SQL agent wastes tokens and
invites wrong joins. Linking narrows the prompt to the relevant tables, in three steps:

1. Lexical matching - words in the question that match table or column names
   ("cities" -> customers.city).
2. Value matching   - words in the question that are actual values stored in the database
   ("Kochi" -> customers.city = 'Kochi'). Also tells the SQL agent the exact spelling.
3. LLM linking      - the model picks tables/columns for meaning the words don't show
   ("revenue" -> orders.amount).

The union of the three is then closed over foreign keys: if two linked tables are only
connected through a third one, the third is added too, so the join is possible.
"""

import difflib
import json
import re
import sqlite3
from collections import deque
from dataclasses import dataclass, field

from app.services.llm import LLMError, ask_llm

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "by", "with", "and", "or", "is", "are",
    "was", "were", "be", "what", "which", "who", "how", "many", "much", "show", "me", "list",
    "give", "find", "get", "all", "each", "per", "top", "most", "least", "best", "from", "that",
    "this", "do", "does", "did", "have", "has", "there", "their", "it", "its", "i", "my", "our",
    "than", "more", "less", "number", "total", "average", "count", "id",
}

MAX_VALUES_PER_COLUMN = 1000
MAX_TEXT_COLUMNS = 60


@dataclass
class LinkResult:
    tables: list[str]
    columns: dict[str, list[str]]                    # table -> columns judged relevant
    values: list[dict] = field(default_factory=list)  # {"table","column","value"}
    reasons: dict[str, list[str]] = field(default_factory=dict)  # table -> why it was linked
    method: str = ""

    def to_dict(self) -> dict:
        return {
            "tables": self.tables,
            "columns": self.columns,
            "values": self.values,
            "reasons": self.reasons,
            "method": self.method,
        }


# ---------- helpers ----------

def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> list[str]:
    return [_singular(w) for w in re.findall(r"[a-z0-9]+", text.lower())]


def _name_words(name: str) -> list[str]:
    # customer_id -> ["customer", "id"]; orderDate -> ["order", "date"]
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return _words(spaced.replace("_", " "))


def build_value_index(conn: sqlite3.Connection, schema: dict) -> list[tuple[str, str, str]]:
    """Distinct short text values per text column: (table, column, value)."""
    index: list[tuple[str, str, str]] = []
    text_columns = [
        (t["name"], c["name"])
        for t in schema["tables"]
        for c in t["columns"]
        if any(k in (c["type"] or "TEXT").upper() for k in ("CHAR", "TEXT", "CLOB", "VARCHAR"))
        and not c["primary_key"]
    ][:MAX_TEXT_COLUMNS]
    for table, column in text_columns:
        rows = conn.execute(
            f'SELECT DISTINCT "{column}" FROM "{table}" '
            f'WHERE typeof("{column}") = \'text\' AND length("{column}") BETWEEN 2 AND 60 '
            f"LIMIT {MAX_VALUES_PER_COLUMN}"
        )
        for (value,) in rows:
            # Dates and numbers stored as text are matched poorly by words; skip them.
            if re.fullmatch(r"[\d\s\-:./]+", value):
                continue
            index.append((table, column, value))
    return index


def _fk_graph(schema: dict) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {t["name"]: set() for t in schema["tables"]}
    for t in schema["tables"]:
        for fk in t["foreign_keys"]:
            other = fk["references"].split(".")[0]
            if other in graph:
                graph[t["name"]].add(other)
                graph[other].add(t["name"])
    return graph


def _shortest_path(graph: dict[str, set[str]], start: str, goal: str) -> list[str]:
    queue, seen = deque([[start]]), {start}
    while queue:
        path = queue.popleft()
        if path[-1] == goal:
            return path
        for nxt in graph[path[-1]] - seen:
            seen.add(nxt)
            queue.append(path + [nxt])
    return []


def connect_tables(schema: dict, tables: set[str]) -> dict[str, str]:
    """Bridge tables needed to join the linked tables: {bridge_table: reason}."""
    graph = _fk_graph(schema)
    linked = sorted(tables)
    bridges: dict[str, str] = {}
    for i, a in enumerate(linked):
        for b in linked[i + 1:]:
            path = _shortest_path(graph, a, b)
            for middle in path[1:-1]:
                if middle not in tables:
                    bridges[middle] = f"joins {a} to {b}"
    return bridges


# ---------- the three linking steps ----------

def lexical_links(question: str, schema: dict) -> dict[str, list[tuple[str | None, str]]]:
    """table -> [(column or None, reason)] for names that appear in the question."""
    q_words = set(_words(question)) - STOPWORDS
    hits: dict[str, list[tuple[str | None, str]]] = {}
    for t in schema["tables"]:
        t_words = set(_name_words(t["name"])) - STOPWORDS
        if t_words and t_words <= q_words:
            hits.setdefault(t["name"], []).append((None, f'table name "{t["name"]}" in question'))
        for c in t["columns"]:
            c_words = set(_name_words(c["name"])) - STOPWORDS
            if c_words and c_words <= q_words:
                hits.setdefault(t["name"], []).append((c["name"], f'column "{c["name"]}" in question'))
    return hits


def _mentions(question: str) -> list[str]:
    """Phrases in the question that may name a stored value: 1-4 word runs that start with a
    capital letter (proper nouns such as "Riverside" or "Fresno Unified") or quoted text."""
    quoted = re.findall(r"[\"'“‘]([^\"'”’]{2,60})[\"'”’]", question)
    words = re.findall(r"[A-Za-z0-9][\w&.-]*", question)
    phrases = []
    for i, w in enumerate(words):
        if not w[0].isupper() or w.lower() in STOPWORDS:
            continue
        for n in range(1, 5):
            chunk = words[i:i + n]
            if len(chunk) == n:
                phrases.append(" ".join(chunk))
    return list(dict.fromkeys(quoted + phrases))


def value_links(question: str, value_index: list[tuple[str, str, str]]) -> list[dict]:
    """Values stored in the database that the question mentions.

    exact   - the value appears in the question as is ("Kochi")
    partial - a capitalised phrase is the start of a value ("Riverside" -> "Riverside Unified")
    fuzzy   - a capitalised phrase is a near spelling of a value ("Fresno Unifed")
    """
    q = question.lower()
    found = []
    for table, column, value in value_index:
        if re.search(rf"(?<![a-z0-9]){re.escape(value.lower())}(?![a-z0-9])", q):
            found.append({"table": table, "column": column, "value": value, "match": "exact"})

    exact_values = {v["value"].lower() for v in found}
    by_lower: dict[str, list[tuple[str, str, str]]] = {}
    for table, column, value in value_index:
        by_lower.setdefault(value.lower(), []).append((table, column, value))
    candidates = list(by_lower)

    for mention in _mentions(question):
        m = mention.lower()
        if m in exact_values or len(m) < 4:
            continue
        partial = [v for v in candidates if v.startswith(m + " ") or v.startswith(m + ",")][:3]
        fuzzy = [] if partial else difflib.get_close_matches(m, candidates, n=2, cutoff=0.88)
        for kind, hits in (("partial", partial), ("fuzzy", fuzzy)):
            for hit in hits:
                if hit in exact_values:
                    continue
                for table, column, value in by_lower[hit][:2]:
                    found.append({"table": table, "column": column, "value": value, "match": kind, "mention": mention})

    # Prefer exact, then longer matches ("New Delhi" over "Delhi"); drop values inside a longer exact match.
    order = {"exact": 0, "partial": 1, "fuzzy": 2}
    found.sort(key=lambda v: (order[v["match"]], -len(v["value"])))
    kept: list[dict] = []
    for v in found:
        inside_longer = any(
            v["value"].lower() in k["value"].lower() and v["value"] != k["value"] and k["match"] == "exact"
            for k in kept
        )
        if not inside_longer and not any(k["value"] == v["value"] and k["column"] == v["column"] for k in kept):
            kept.append(v)
    return kept[:20]


def category_values(value_index: list[tuple[str, str, str]], max_values: int = 20) -> dict[tuple[str, str], list[str]]:
    """Text columns with only a few distinct values ("category" columns) and those values."""
    per_column: dict[tuple[str, str], list[str]] = {}
    for table, column, value in value_index:
        per_column.setdefault((table, column), []).append(value)
    return {
        key: sorted(values)
        for key, values in per_column.items()
        if len(values) <= max_values and all(len(v) <= 40 for v in values)
    }


LINK_PROMPT = """You are the schema-linking step of a text-to-SQL system.
Given a database schema and a question, list the tables and columns needed to write the SQL.
Include tables needed for joins. Use only names that exist in the schema.
Reply with JSON only: {"tables": ["table", ...], "columns": ["table.column", ...]}

Schema:
{schema}"""


def compact_schema(schema: dict, descriptions: dict | None = None) -> str:
    """One line per table; columns get their readable name when documented (SOC "School ownership code")."""
    descriptions = descriptions or {}
    lines = []
    for t in schema["tables"]:
        docs = descriptions.get(t["name"].lower(), {})

        def col(c):
            readable = docs.get(c["name"].lower(), {}).get("name") or docs.get(c["name"].lower(), {}).get("description", "")
            readable = readable[:60]
            return f'{c["name"]} {c["type"]}' + (f' "{readable}"' if readable else "")

        cols = ", ".join(col(c) for c in t["columns"])
        lines.append(f'{t["name"]}({cols})')
        for fk in t["foreign_keys"]:
            lines.append(f'  {t["name"]}.{fk["column"]} -> {fk["references"]}')
    return "\n".join(lines)


def llm_links(question: str, schema: dict, descriptions: dict | None = None) -> tuple[set[str], dict[str, set[str]]]:
    prompt = LINK_PROMPT.replace("{schema}", compact_schema(schema, descriptions))
    reply = ask_llm(prompt, question, json_mode=True)
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    data = json.loads(match.group(0) if match else reply)

    valid = {t["name"]: {c["name"] for c in t["columns"]} for t in schema["tables"]}
    lower = {name.lower(): name for name in valid}
    tables = {lower[t.lower()] for t in data.get("tables", []) if isinstance(t, str) and t.lower() in lower}
    columns: dict[str, set[str]] = {}
    for item in data.get("columns", []):
        if not isinstance(item, str) or "." not in item:
            continue
        t, c = item.split(".", 1)
        t = lower.get(t.strip().lower())
        if t and c.strip() in valid[t]:
            columns.setdefault(t, set()).add(c.strip())
            tables.add(t)
    return tables, columns


# ---------- putting it together ----------

def link_schema(
    question: str,
    schema: dict,
    value_index: list[tuple[str, str, str]],
    descriptions: dict | None = None,
) -> LinkResult:
    reasons: dict[str, list[str]] = {}
    columns: dict[str, set[str]] = {}
    methods = []

    def add(table: str, reason: str, column: str | None = None):
        if reason not in reasons.setdefault(table, []):
            reasons[table].append(reason)
        if column:
            columns.setdefault(table, set()).add(column)

    for table, items in lexical_links(question, schema).items():
        for column, reason in items:
            add(table, reason, column)
    if reasons:
        methods.append("lexical")

    values = value_links(question, value_index)
    for v in values:
        how = "found in" if v["match"] == "exact" else f'({v["match"]} match for "{v["mention"]}") in'
        add(v["table"], f'value "{v["value"]}" {how} {v["column"]}', v["column"])
    if values:
        methods.append("value")

    try:
        llm_tables, llm_columns = llm_links(question, schema, descriptions)
        for t in llm_tables:
            add(t, "chosen by the linking model")
        for t, cols in llm_columns.items():
            columns.setdefault(t, set()).update(cols)
        methods.append("llm")
    except (LLMError, ValueError, json.JSONDecodeError):
        pass  # lexical + value links still work without the model

    if not reasons:
        # Nothing matched: fall back to the whole schema rather than guessing.
        all_tables = [t["name"] for t in schema["tables"]]
        return LinkResult(all_tables, {}, values, {t: ["no match, using all tables"] for t in all_tables}, "fallback")

    for bridge, reason in connect_tables(schema, set(reasons)).items():
        add(bridge, reason)

    order = [t["name"] for t in schema["tables"] if t["name"] in reasons]
    return LinkResult(
        tables=order,
        columns={t: sorted(columns.get(t, set())) for t in order if columns.get(t)},
        values=values,
        reasons={t: reasons[t] for t in order},
        method="+".join(methods),
    )
