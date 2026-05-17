"""Attribute file edits to AI or human using session-captured evidence only.

No external tool dependency (no Claude Code logs, no editor plugins).
Evidence sources — all from trace's own capture:

  1. Scene index labels: windows tagged 'ai_assistant' during a file's save
     window → agent wrote in that file.
  2. Transcript: developer said AI-invocation keywords ("claude", "copilot",
     "have it", "let it", "ask it") within 60s of a file save → agent.
  3. Timeline moments: 'research' moment active during save → possible AI
     lookup, contributes weak agent signal.
  4. Fallback: file saved during session but no AI signal → human.
     File not saved at all during session → unknown.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("trace.contribution.scanner")

# Spoken keywords that indicate the developer invoked an AI tool.
_AI_KEYWORDS = re.compile(
    r"\b(claude|copilot|chatgpt|gpt|gemini|cursor|codeium|tabnine|"
    r"have it|let it|ask it|ai (wrote|did|added|fixed|generated)|"
    r"it (wrote|added|generated|fixed))\b",
    re.IGNORECASE,
)


def _ensure_tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def collect_agent_edits(
    project_dir: Path,
    *,
    started_at: datetime,
    stopped_at: datetime,
    timeline=None,
    transcript=None,
    scenes: list[dict] | None = None,
) -> dict[str, set[str]]:
    """Return {relative_file_path: {"__agent__"}} for files with AI signal.

    Value is a sentinel set so mapper.classify can still do basename matching.
    We no longer return line-level text (session recording doesn't give us
    that). Instead mapper uses file-level signal: if file is in the returned
    dict → agent/mixed; if not but file was saved → human; else → unknown.
    """
    started_at = _ensure_tz(started_at)
    stopped_at = _ensure_tz(stopped_at)

    # ── 1. Collect file save events from session store ──────────────────────
    # SessionStore saves events_saves.jsonl with {ts, path} records.
    # We find them by looking for the jsonl adjacent to project_dir's session.
    # However, scanner receives project_dir only — not session_id.
    # Walk up ~/.trace/sessions/ to find sessions whose project_dir matches.
    from trace_cli.session.store import SessionStore
    store = SessionStore()
    session_saves: dict[str, list[float]] = {}  # rel_path → [save_ts_seconds_offset]
    session_project_dir: Path | None = None

    for sid in store.list_sessions():
        try:
            meta = store.read_metadata(sid)
            if not meta.project_dir:
                continue
            mp = Path(meta.project_dir).resolve()
            if mp != project_dir.resolve():
                continue
            if _ensure_tz(meta.started_at) != started_at:
                continue
            session_project_dir = mp
            session_start_unix = started_at.timestamp()
            saves_path = store.session_dir(sid) / "events_saves.jsonl"
            if saves_path.exists():
                import json
                for line in saves_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        raw_path = ev.get("path", "")
                        if not raw_path:
                            continue
                        # Compute offset from t_unix (absolute) relative to session start.
                        t_unix = float(ev.get("t_unix", 0))
                        offset = t_unix - session_start_unix if t_unix > 0 else 0.0
                        # Make relative to project_dir.
                        try:
                            rel = str(Path(raw_path).relative_to(project_dir.resolve()))
                        except ValueError:
                            rel = raw_path
                        session_saves.setdefault(rel, []).append(offset)
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            continue

    if not session_saves:
        log.info("no save events found for project_dir=%s; all files unknown", project_dir)
        return {}

    session_duration = (stopped_at - started_at).total_seconds()

    # ── 2. Build AI-signal windows from scenes ───────────────────────────────
    ai_windows: list[tuple[float, float]] = []  # (start_s, end_s)
    for scene in (scenes or []):
        label = ""
        desc = scene.get("description", "") or ""
        # Scene descriptions are JSON from our classifier prompt.
        try:
            import json as _json
            d = _json.loads(desc)
            label = str(d.get("label", "")).lower()
        except Exception:  # noqa: BLE001
            label = desc.lower()
        if "ai_assistant" in label:
            s = float(scene.get("start", scene.get("start_seconds", 0)) or 0)
            e = float(scene.get("end", scene.get("end_seconds", s + 10)) or s + 10)
            ai_windows.append((s, e))

    # ── 3. Build AI-signal windows from transcript keywords ──────────────────
    for seg in getattr(transcript, "segments", []) or []:
        text = seg.text or ""
        if _AI_KEYWORDS.search(text):
            s = float(getattr(seg, "start_seconds", 0))
            e = float(getattr(seg, "end_seconds", s + 5))
            # Expand window ±30s around keyword utterance.
            ai_windows.append((max(0, s - 30), min(session_duration, e + 30)))

    # Research moments are NOT an AI-writing signal (reading docs != agent wrote code).

    log.info("ai_windows: %d (scenes+transcript)", len(ai_windows))

    # ── 5. Classify each saved file ──────────────────────────────────────────
    agent_files: dict[str, set[str]] = {}
    for rel_path, save_offsets in session_saves.items():
        for offset in save_offsets:
            for ws, we in ai_windows:
                if ws - 5 <= offset <= we + 5:
                    agent_files[rel_path] = {"__agent__"}
                    log.debug("agent signal: %s saved at %.1fs, ai_window [%.1f-%.1f]", rel_path, offset, ws, we)
                    break
            if rel_path in agent_files:
                break

    log.info(
        "agent files: %d / %d total saved files",
        len(agent_files), len(session_saves),
    )
    return agent_files


def _all_saved_files(
    project_dir: Path,
    *,
    started_at: datetime,
    stopped_at: datetime,
) -> set[str]:
    """Return rel paths of all files saved during session (for human vs unknown split)."""
    started_at = _ensure_tz(started_at)
    from trace_cli.session.store import SessionStore
    store = SessionStore()
    saved: set[str] = set()
    for sid in store.list_sessions():
        try:
            meta = store.read_metadata(sid)
            if not meta.project_dir:
                continue
            if Path(meta.project_dir).resolve() != project_dir.resolve():
                continue
            if _ensure_tz(meta.started_at) != started_at:
                continue
            saves_path = store.session_dir(sid) / "events_saves.jsonl"
            if saves_path.exists():
                import json
                for line in saves_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        raw_path = ev.get("path", "")
                        if not raw_path:
                            continue
                        try:
                            rel = str(Path(raw_path).relative_to(project_dir.resolve()))
                        except ValueError:
                            rel = raw_path
                        saved.add(rel)
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            continue
    return saved
