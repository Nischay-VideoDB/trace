"""Decision Replay service: given (file_path, start_line, end_line), return
ordered clip intervals during the recorded session where that file region was
touched.

Strategy:
  1. Validate range (R5.6).
  2. Load session save events from events_saves.jsonl. Filter by file basename.
  3. For each contiguous group of save events, form interval
     [save_t - 8s, save_t + 4s] in session time (subtract started_at).
  4. Augment via video.search(index_type=scene, query=basename + lines) to add
     visual evidence of the editor on that file.
  5. Generate bounded clip URLs via video.generate_stream(timeline=[(s,e)]).
  6. Return sorted by start ascending.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from trace_cli.session.models import SaveEvent
from trace_cli.session.store import SessionStore
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.replay")


class InvalidRange(Exception):
    pass


class FileNotInSession(Exception):
    pass


@dataclass
class ReplayInterval:
    start_seconds: float
    end_seconds: float
    description: str
    clip_url: str

    def to_json(self) -> dict:
        return {
            "start_seconds": round(self.start_seconds, 2),
            "end_seconds": round(self.end_seconds, 2),
            "description": self.description,
            "clip_url": self.clip_url,
        }


def validate_range(start_line: int, end_line: int) -> None:
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        raise InvalidRange(f"line numbers must be integers")
    if start_line < 1 or end_line < 1:
        raise InvalidRange(f"line numbers must be >= 1 (got {start_line}, {end_line})")
    if start_line > end_line:
        raise InvalidRange(f"start_line ({start_line}) > end_line ({end_line})")


def query(
    session_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    pad_before: float = 8.0,
    pad_after: float = 4.0,
) -> list[ReplayInterval]:
    validate_range(start_line, end_line)

    store = SessionStore()
    meta = store.read_metadata(session_id)
    if not meta.video_id:
        raise FileNotInSession(f"session {session_id} not yet indexed (no video_id)")

    started = meta.started_at.timestamp()

    # 1. Save-event evidence: any save whose basename matches.
    file_basename = os.path.basename(file_path)
    saves_raw = store.read_events(session_id, "saves")
    matched: list[SaveEvent] = []
    for d in saves_raw:
        try:
            ev = SaveEvent.model_validate(d)
        except Exception:  # noqa: BLE001
            continue
        if os.path.basename(ev.path) == file_basename or ev.path == file_path:
            matched.append(ev)

    if not matched:
        # Search VideoDB scenes for evidence the file was on screen even if
        # we did not see a save event.
        client = VideoDBClient()
        video = client.get_video(meta.video_id)
        try:
            sr = client.search_video_scene(
                video,
                f"{file_basename} editor lines {start_line} to {end_line}",
                score_threshold=0.2,
            )
            shots = getattr(sr, "get_shots", lambda: [])() or []
        except Exception:
            shots = []
        if not shots:
            raise FileNotInSession(f"no record of {file_path} in session {session_id}")
        # Construct intervals from scene shots only.
        intervals: list[ReplayInterval] = []
        for sh in shots[:5]:
            s = float(getattr(sh, "start", 0.0) or 0.0)
            e = float(getattr(sh, "end", 0.0) or 0.0)
            if e <= s:
                e = s + 5.0
            try:
                url = client.video_clip_url(video, s, e)
            except Exception:
                url = "(clip unavailable)"
            intervals.append(ReplayInterval(
                start_seconds=s,
                end_seconds=e,
                description=f"scene match: {file_basename} visible on screen",
                clip_url=url,
            ))
        intervals.sort(key=lambda x: x.start_seconds)
        return intervals

    # 2. Group close save events together (within 10s of each other).
    matched.sort(key=lambda e: e.t_unix)
    groups: list[list[SaveEvent]] = []
    for ev in matched:
        if groups and ev.t_unix - groups[-1][-1].t_unix < 10.0:
            groups[-1].append(ev)
        else:
            groups.append([ev])

    # 3. Build intervals + clip URLs.
    client = VideoDBClient()
    video = client.get_video(meta.video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    intervals: list[ReplayInterval] = []
    for grp in groups:
        first_t = grp[0].t_unix - started
        last_t = grp[-1].t_unix - started
        s = max(0.0, first_t - pad_before)
        e = min(video_length - 0.05 if video_length > 0 else last_t + pad_after, last_t + pad_after)
        if e <= s:
            continue
        n = len(grp)
        desc = f"{n} save{'s' if n > 1 else ''} of {file_basename} at lines {start_line}-{end_line}"
        try:
            url = client.video_clip_url(video, s, e)
        except Exception as ex:  # noqa: BLE001
            log.warning("clip url gen failed [%.1f-%.1f] (%s)", s, e, ex)
            url = "(clip unavailable)"
        intervals.append(ReplayInterval(
            start_seconds=s,
            end_seconds=e,
            description=desc,
            clip_url=url,
        ))

    intervals.sort(key=lambda x: x.start_seconds)
    return intervals
