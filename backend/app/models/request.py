"""Shapes of the API's request and response (FastAPI validates these automatically)."""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    results: list[list[Any]]
    explanation: str
    truncated: bool = False
    # What the agents did: linked tables, every SQL attempt and its error, timings.
    trace: dict[str, Any] = {}


class RunSqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)


class RunSqlResponse(BaseModel):
    sql: str
    columns: list[str]
    results: list[list[Any]]
    truncated: bool = False
