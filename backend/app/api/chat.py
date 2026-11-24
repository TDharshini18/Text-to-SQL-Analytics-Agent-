"""The API endpoints. The agent logic itself lives in agents/pipeline.py.

GET  /schema       tables, columns, keys and example rows
POST /chat         question -> full answer (runs the whole agent pipeline)
POST /chat/stream  same, but streams each agent step as one JSON object per line (NDJSON)
POST /run-sql      run SQL the user edited (same safety check, read-only, no LLM)
"""

import json
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import config
from app.agents.pipeline import PipelineError, run_pipeline
from app.agents.schema_agent import get_schema
from app.database.connection import get_connection
from app.models.request import ChatRequest, ChatResponse, RunSqlRequest, RunSqlResponse
from app.services.llm import LLMError
from app.services.sql_executor import execute_sql
from app.services.sql_validator import UnsafeSQLError, validate_sql

router = APIRouter()


def open_db() -> sqlite3.Connection:
    try:
        return get_connection(config.DB_PATH)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _history(req: ChatRequest) -> list[dict]:
    return [t.model_dump() for t in req.history]


@router.get("/schema")
def schema():
    conn = open_db()
    try:
        return get_schema(conn) | {"database": config.DB_PATH.name}
    finally:
        conn.close()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    conn = open_db()
    try:
        for event in run_pipeline(conn, req.question, conversation=_history(req)):
            if event["type"] == "result":
                return event["response"]
        raise HTTPException(status_code=500, detail="The pipeline ended without a result.")
    except PipelineError as e:
        raise HTTPException(status_code=422, detail={"message": e.message, "sql": e.sql}) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        conn.close()


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    conn = open_db()

    def events() -> Iterator[str]:
        try:
            for event in run_pipeline(conn, req.question, conversation=_history(req)):
                yield json.dumps(event, default=str) + "\n"
        except PipelineError as e:
            yield json.dumps({"type": "error", "message": e.message, "sql": e.sql}) + "\n"
        except LLMError as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
        except Exception as e:  # keep the stream well-formed even on a bug
            yield json.dumps({"type": "error", "message": f"Unexpected error: {e}"}) + "\n"
        finally:
            conn.close()

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/run-sql", response_model=RunSqlResponse)
def run_sql(req: RunSqlRequest):
    conn = open_db()
    try:
        sql = req.sql.strip().rstrip(";").strip()
        validate_sql(sql)
        columns, rows = execute_sql(conn, sql)
        return {"sql": sql, "columns": columns, "results": rows, "truncated": len(rows) >= config.MAX_ROWS}
    except (UnsafeSQLError, sqlite3.Error) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        conn.close()
