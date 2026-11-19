"""Reads the database structure: tables, columns, types, keys and a few example rows."""

import sqlite3


def read_schema(conn: sqlite3.Connection) -> dict:
    tables = []
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for name in names:
        # PRAGMA table_info rows: (cid, name, type, notnull, default, pk)
        columns = [
            {"name": c[1], "type": c[2] or "TEXT", "primary_key": bool(c[5])}
            for c in conn.execute(f'PRAGMA table_info("{name}")')
        ]
        # PRAGMA foreign_key_list rows: (id, seq, table, from, to, ...)
        foreign_keys = [
            {"column": fk[3], "references": f"{fk[2]}.{fk[4]}"}
            for fk in conn.execute(f'PRAGMA foreign_key_list("{name}")')
        ]
        sample_rows = [
            [str(v)[:40] for v in row]
            for row in conn.execute(f'SELECT * FROM "{name}" LIMIT 3')
        ]
        tables.append(
            {
                "name": name,
                "columns": columns,
                "foreign_keys": foreign_keys,
                "sample_rows": sample_rows,
            }
        )
    return {"tables": tables}
