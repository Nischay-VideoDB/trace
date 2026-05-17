"""FastAPI app: trace web server.

Routes:
  GET /              - landing page
  GET /api/sessions  - list known session ids
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from trace_cli.session.store import SessionStore

log = logging.getLogger("trace.web")

app = FastAPI(title="trace", version="0.1.0", docs_url="/api-docs", redoc_url=None)

LANDING_DIR = Path(__file__).resolve().parent.parent.parent / "landing"
if LANDING_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(LANDING_DIR)), name="landing-static")


def _serve_landing(name: str) -> HTMLResponse:
    path = LANDING_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return FileResponse(str(path), media_type="text/html")


@app.get("/", include_in_schema=False)
async def root():
    return _serve_landing("index.html")


@app.get("/docs", include_in_schema=False)
async def docs_page():
    return _serve_landing("docs.html")


@app.get("/api/sessions")
async def list_sessions() -> list[str]:
    return SessionStore().list_sessions()
