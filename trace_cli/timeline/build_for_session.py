"""Glue: read session artifacts, run classifiers, merge, persist timeline.json."""
from __future__ import annotations

import logging
from datetime import datetime

from trace_cli.session.models import (
    SaveEvent,
    Transcript,
    TranscriptSegment,
    WindowEvent,
)
from trace_cli.session.store import SessionStore
from trace_cli.timeline.builder import Timeline, merge, to_json
from trace_cli.timeline.classifiers import (
    progress_candidates,
    research_candidates,
    speech_candidates,
    stuck_candidates,
)

log = logging.getLogger("trace.timeline.build")


def _started_at_unix(store: SessionStore, session_id: str) -> float:
    meta = store.read_metadata(session_id)
    return meta.started_at.timestamp()


def _session_end_seconds(store: SessionStore, session_id: str) -> float:
    meta = store.read_metadata(session_id)
    if meta.stopped_at is None:
        # Fall back to last heartbeat or mp4 duration probe.
        hbs = store.read_events(session_id, "heartbeat")
        if hbs:
            return float(hbs[-1].get("elapsed_seconds", 0.0))
        return 0.0
    return (meta.stopped_at - meta.started_at).total_seconds()


def _load_transcript(store: SessionStore, session_id: str) -> list[TranscriptSegment]:
    p = store.transcript_path(session_id)
    if not p.exists():
        return []
    try:
        return Transcript.model_validate_json(p.read_text(encoding="utf-8")).segments
    except Exception as e:  # noqa: BLE001
        log.warning("transcript load failed: %s", e)
        return []


def build_timeline_for_session(session_id: str, *, store: SessionStore | None = None) -> Timeline:
    store = store or SessionStore()
    started = _started_at_unix(store, session_id)
    end_s = _session_end_seconds(store, session_id)

    saves = [SaveEvent.model_validate(d) for d in store.read_events(session_id, "saves")]
    windows = [WindowEvent.model_validate(d) for d in store.read_events(session_id, "windows")]
    segments = _load_transcript(store, session_id)

    cands = (
        progress_candidates(saves, started, end_s)
        + speech_candidates(segments)
        + research_candidates(windows, started, end_s)
        + stuck_candidates(segments, saves, started, end_s)
    )
    log.info(
        "candidates: progress=%d speech=%d research=%d stuck=%d session_end=%.2fs",
        sum(1 for c in cands if c.category == "progress"),
        sum(1 for c in cands if c.category == "speech"),
        sum(1 for c in cands if c.category == "research"),
        sum(1 for c in cands if c.category == "stuck"),
        end_s,
    )

    tl = merge(cands, session_end_seconds=end_s, session_id=session_id)
    store.timeline_path(session_id).write_text(to_json(tl), encoding="utf-8")
    log.info("wrote timeline with %d moments", len(tl.moments))
    return tl
