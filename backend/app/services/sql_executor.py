"""Runs a validated query with a time limit and a row limit."""

import sqlite3
import time

from app import config


def execute_sql(conn: sqlite3.Connection, sql: str) -> tuple[list[str], list[list]]:
    deadline = time.monotonic() + config.QUERY_TIMEOUT_S
    # SQLite calls this every 10,000 steps; returning 1 stops the query.
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = [list(row) for row in cursor.fetchmany(config.MAX_ROWS)]
        return columns, rows
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise sqlite3.OperationalError(
                f"Query took longer than {config.QUERY_TIMEOUT_S} seconds and was stopped."
            ) from e
        raise
    finally:
        conn.set_progress_handler(None, 0)
