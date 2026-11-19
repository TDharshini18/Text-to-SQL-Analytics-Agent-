"""FastAPI app. Run from the backend folder:  uvicorn app.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router

app = FastAPI(title="SQL AI Assistant")

# Allow the Angular dev server (localhost:4200) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
