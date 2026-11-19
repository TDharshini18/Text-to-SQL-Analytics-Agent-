"""Settings, read from the .env file in the backend folder."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

# Path to the SQLite database to query. Relative paths are relative to the backend folder.
_db = Path(os.getenv("DB_PATH", "data/sample.sqlite").strip())
DB_PATH = _db if _db.is_absolute() else BACKEND_DIR / _db

MAX_ROWS = 500           # rows returned to the UI
QUERY_TIMEOUT_S = 10     # a query running longer than this is stopped
