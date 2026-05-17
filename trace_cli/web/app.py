"""FastAPI app: Decision Replay UI + JSON API.

Routes:
  GET /              - redirect to /replay
  GET /replay        - single-page UI: pick session, file, line range, view clips
  GET /api/sessions  - list known session ids
  GET /api/replay    - JSON: ?session_id=&file=&start=&end=
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from trace_cli.decision_replay.service import (
    FileNotInSession,
    InvalidRange,
    ReplayInterval,
    query as replay_query,
)
from trace_cli.session.store import SessionStore

log = logging.getLogger("trace.web")

app = FastAPI(title="trace", version="0.1.0", docs_url="/api-docs", redoc_url=None)

LANDING_DIR = Path(__file__).resolve().parent.parent.parent / "landing"
if LANDING_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(LANDING_DIR)), name="landing-static")

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>trace - Decision Replay</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 920px;
         margin: 32px auto; padding: 0 16px; color: #111; background: #fafafa; }
  h1 { font-size: 22px; }
  form { display: grid; grid-template-columns: 1fr; gap: 8px; margin-bottom: 16px;
         background: #fff; padding: 16px; border: 1px solid #ddd; border-radius: 8px; }
  label { font-size: 12px; color: #555; }
  input, select { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; }
  button { padding: 10px 16px; background: #0a0a0a; color: #fff; border: 0;
           border-radius: 4px; cursor: pointer; font-size: 14px; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .clip { background: #fff; padding: 12px; border: 1px solid #ddd; border-radius: 8px;
          margin: 12px 0; }
  .clip h3 { margin: 0 0 4px 0; font-size: 14px; }
  .meta { color: #666; font-size: 12px; margin-bottom: 8px; }
  video { width: 100%; max-width: 720px; border-radius: 4px; background: #000; }
  .err { color: #b00; padding: 12px; background: #fee; border-radius: 8px; }
  pre { background: #f3f3f3; padding: 8px; border-radius: 4px; overflow-x: auto; }
</style>
</head>
<body>
<h1>trace - Decision Replay</h1>
<p>Click any code block in your PR to see the recorded moments when those lines were edited.</p>

<form id="f">
  <label>session id</label>
  <select id="session"></select>
  <label>file path (or basename)</label>
  <input id="file" placeholder="e.g. auth.py" required />
  <label>start line</label>
  <input id="start" type="number" min="1" value="1" required />
  <label>end line</label>
  <input id="end" type="number" min="1" value="100" required />
  <button type="submit">show clips</button>
</form>

<div id="out"></div>

<script>
async function loadSessions() {
  const r = await fetch('/api/sessions');
  const sids = await r.json();
  const sel = document.getElementById('session');
  sel.innerHTML = '';
  for (const s of sids) {
    const o = document.createElement('option');
    o.value = s; o.textContent = s;
    sel.appendChild(o);
  }
}

document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const sid = document.getElementById('session').value;
  const file = document.getElementById('file').value;
  const start = document.getElementById('start').value;
  const end = document.getElementById('end').value;
  const out = document.getElementById('out');
  out.innerHTML = '<p>loading...</p>';
  try {
    const url = `/api/replay?session_id=${encodeURIComponent(sid)}&file=${encodeURIComponent(file)}&start=${start}&end=${end}`;
    const r = await fetch(url);
    if (!r.ok) {
      const e = await r.json();
      out.innerHTML = `<div class="err">${e.detail || 'error'}</div>`;
      return;
    }
    const data = await r.json();
    if (!data.length) {
      out.innerHTML = '<div class="err">no clips found for this file/range</div>';
      return;
    }
    out.innerHTML = data.map(c =>
      `<div class="clip">
         <h3>${c.description}</h3>
         <div class="meta">[${c.start_seconds.toFixed(1)} - ${c.end_seconds.toFixed(1)}s]</div>
         <video controls src="${c.clip_url}" preload="metadata"></video>
         <div class="meta"><a href="${c.clip_url}" target="_blank">open clip</a></div>
       </div>`).join('');
  } catch (err) {
    out.innerHTML = `<div class="err">${err.message}</div>`;
  }
});

loadSessions();
</script>
</body>
</html>
"""


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


@app.get("/replay", response_class=HTMLResponse)
async def replay_ui() -> str:
    return INDEX_HTML


@app.get("/api/sessions")
async def list_sessions() -> list[str]:
    return SessionStore().list_sessions()


@app.get("/api/replay")
async def api_replay(
    session_id: str = Query(...),
    file: str = Query(...),
    start: int = Query(..., ge=1),
    end: int = Query(..., ge=1),
):
    try:
        intervals: list[ReplayInterval] = replay_query(session_id, file, start, end)
    except InvalidRange as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotInSession as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"session not found: {e}")
    except Exception as e:  # noqa: BLE001
        log.exception("replay failed")
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse([i.to_json() for i in intervals])
