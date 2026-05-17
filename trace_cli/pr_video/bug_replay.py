"""Replay the Bug: detect a failure -> error -> fix arc and assemble a mini clip.

Heuristic detection of a bug story:
  1. Find a 'stuck' moment OR a transcript segment containing failure language
     ('this is wrong', 'error', 'doesn't work', 'failing')
  2. Look for a scene-index window nearby that shows a terminal with errors
  3. Look for the next progress moment after the failure (the fix)
  4. Stitch: failure clip + terminal-error clip + fix clip into one short
     video via videodb.editor.Timeline with badges

If no clear bug arc found, returns None and the caller skips posting.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from videodb.editor import (
    AudioAsset,
    Background,
    Clip,
    Font,
    Position,
    TextAsset,
    Timeline,
    Track,
    VideoAsset,
)

from trace_cli.session.models import TaggedMoment, Transcript
from trace_cli.session.models import Timeline as SessionTimeline
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.bug_replay")

FAILURE_RE = re.compile(
    r"\b(not working|doesn'?t work|this is wrong|wait[, ]+this|"
    r"failing|error|exception|broke|crash|wrong output)\b",
    re.IGNORECASE,
)


@dataclass
class BugArc:
    failure_t: float
    error_t: float | None
    fix_t: float | None
    failure_evidence: str
    error_evidence: str
    fix_evidence: str


def _scenes_with_errors(scenes: list[dict]) -> list[tuple[float, float, str]]:
    """Parse the fenced-JSON scene descriptions and return windows with errors."""
    out: list[tuple[float, float, str]] = []
    fenced = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    for s in scenes:
        desc = s.get("description") or ""
        m = fenced.search(desc)
        raw = m.group(1) if m else desc
        try:
            d = json.loads(raw) if raw.strip().startswith("{") else {}
        except Exception:  # noqa: BLE001
            d = {}
        errs = d.get("errors") or []
        if errs:
            text = str(errs[0])[:120]
            out.append((float(s.get("start", 0.0)), float(s.get("end", 0.0)), text))
    return out


def detect_bug_arc(
    timeline: SessionTimeline,
    transcript: Transcript,
    scenes: list[dict],
) -> BugArc | None:
    # 1. Find failure point: stuck moment OR transcript failure phrase
    failure_t: float | None = None
    failure_ev = ""

    stuck = next((m for m in timeline.moments if m.category == "stuck"), None)
    if stuck:
        failure_t = stuck.start_seconds
        failure_ev = stuck.evidence[:160]

    if failure_t is None:
        for seg in transcript.segments:
            if FAILURE_RE.search(seg.text or ""):
                failure_t = seg.start_seconds
                failure_ev = seg.text.strip()[:160]
                break

    if failure_t is None:
        return None

    # 2. Find a terminal-with-error scene window within +/- 60s
    error_t: float | None = None
    error_ev = ""
    for s, e, text in _scenes_with_errors(scenes):
        if abs(s - failure_t) < 60:
            error_t = s
            error_ev = text
            break

    # 3. Find a progress moment (the fix). Prefer the next save AFTER failure,
    # but fall back to the LAST save before failure if none after (e.g. when
    # stuck moment came after the actual fix attempt).
    fix_t: float | None = None
    fix_ev = ""
    after = [m for m in timeline.moments if m.category == "progress" and m.confidence > 0 and m.start_seconds > failure_t]
    before = [m for m in timeline.moments if m.category == "progress" and m.confidence > 0 and m.start_seconds <= failure_t]
    if after:
        fix_t = after[0].start_seconds
        fix_ev = after[0].evidence[:160] or "code saved"
    elif before:
        fix_t = before[-1].start_seconds
        fix_ev = before[-1].evidence[:160] or "code saved"
    else:
        return None

    return BugArc(
        failure_t=failure_t,
        error_t=error_t,
        fix_t=fix_t,
        failure_evidence=failure_ev,
        error_evidence=error_ev,
        fix_evidence=fix_ev,
    )


def render_bug_clip(
    client: VideoDBClient,
    video_id: str,
    arc: BugArc,
    pr_title: str,
) -> tuple[str, str] | None:
    """Build a 30-45s mini video showing failure -> error -> fix. Returns (hls_url, narration)."""
    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    if video_length <= 0:
        return None

    def _span(t: float, before: float = 4.0, after: float = 8.0) -> tuple[float, float]:
        s = max(0.0, t - before)
        e = min(video_length - 0.05, t + after)
        if e <= s:
            e = s + 5.0
        return s, e

    segments: list[tuple[float, float, str, str]] = []
    fs, fe = _span(arc.failure_t)
    segments.append((fs, fe, "FAILURE", arc.failure_evidence))
    if arc.error_t is not None:
        es, ee = _span(arc.error_t, before=2.0, after=8.0)
        segments.append((es, ee, "ERROR", arc.error_evidence))
    if arc.fix_t is not None:
        xs, xe = _span(arc.fix_t, before=3.0, after=8.0)
        segments.append((xs, xe, "FIX", arc.fix_evidence))

    # One narration line for the whole arc, kept tight
    narration_text = (
        f"Here is the bug story in {pr_title}. "
        f"First, I hit the failure. {arc.failure_evidence[:120]}. "
    )
    if arc.error_t is not None:
        narration_text += f"The terminal showed {arc.error_evidence[:120]}. "
    if arc.fix_t is not None:
        narration_text += f"Then I applied the fix and saved. "
    narration_text = narration_text[:600]

    try:
        audio = client.generate_voice(text=narration_text, voice="male_1")
        audio_id = getattr(audio, "id", "")
        audio_len = float(getattr(audio, "length", 0.0) or 0.0)
    except Exception as e:  # noqa: BLE001
        log.warning("bug replay TTS failed (%s); skipping clip", e)
        return None

    tl = Timeline(client._conn)
    video_track = Track(z_index=0)
    audio_track = Track(z_index=1)
    badge_track = Track(z_index=2)

    cursor = 0
    total_dur = 0.0
    for s, e, badge, _ev in segments:
        dur = max(2.0, e - s)
        v = VideoAsset(id=video_id, start=s, volume=0.0)
        video_track.add_clip(cursor, Clip(asset=v, duration=dur))
        try:
            t_asset = TextAsset(
                text=f"trace - BUG REPLAY - {badge}",
                font=Font(family="Clear Sans", size=32, color="#FFFFFF", opacity=1.0),
                background=Background(width=0.0, height=0.0, color="#000000", opacity=0.7),
            )
            badge_track.add_clip(cursor, Clip(asset=t_asset, duration=dur, position=Position.top_left, opacity=0.9))
        except Exception:  # noqa: BLE001
            pass
        cursor += int(round(dur))
        total_dur += dur

    if audio_id and audio_len > 0:
        a = AudioAsset(id=audio_id, start=0, volume=1.0)
        audio_track.add_clip(0, Clip(asset=a, duration=min(audio_len, total_dur)))

    tl.add_track(video_track)
    tl.add_track(audio_track)
    tl.add_track(badge_track)
    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        log.warning("bug replay timeline render failed (%s)", e)
        return None
    return url, narration_text
