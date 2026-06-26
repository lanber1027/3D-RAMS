from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent import run_site_briefing


app = FastAPI(title="3D-RAMS Demo1 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "3d-rams-demo1"}


@app.post("/api/run")
def run_agent(payload: dict[str, Any]) -> dict[str, Any]:
    return run_site_briefing(payload)

