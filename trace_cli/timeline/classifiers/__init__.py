"""Four classifiers feeding the timeline merger.

progress: bracket each editor save event with +/- 5s (R3.5).
speech: per transcript segment with >=3 words and duration in [1,60]s (R3.6).
research: contiguous run of >=15s where active window is non-editor reference
          content (R3.4). Uses hyprctl window events as evidence in v1
          (without per-frame VideoDB scene classification this is a heuristic).
stuck:    >=90s with no save event AND >=1 uncertain transcript segment (R3.3).
          Uncertainty heuristic in v1: phrases like "not sure", "why is this",
          "hmm", "what the". Anthropic upgrade later if needed.
"""
from __future__ import annotations

import re
from typing import Iterable

from trace_cli.session.models import SaveEvent, TranscriptSegment, WindowEvent
from trace_cli.timeline.builder import Candidate

# Crude uncertainty markers; replace with LLM classifier later.
_UNCERTAIN_RE = re.compile(
    r"\b(not sure|why (?:is|does|isn'?t|doesn'?t)|hmm+|what the|"
    r"i (?:think|don'?t know|wonder)|maybe|that'?s weird|"
    r"this is strange|stuck|confused|no idea)\b",
    re.IGNORECASE,
)

_EDITOR_CLASS_RE = re.compile(
    r"^(code|code-oss|cursor|jetbrains|intellij|pycharm|webstorm|"
    r"sublime_text|gnome-text-editor|gedit|kate|nvim|neovide|"
    r"alacritty|kitty|wezterm|foot|gnome-terminal|konsole)",
    re.IGNORECASE,
)

_REFERENCE_CLASS_RE = re.compile(
    r"^(firefox|librewolf|chromium|google-chrome|brave|vivaldi|"
    r"qutebrowser|epiphany|safari|edge|zen)",
    re.IGNORECASE,
)


def progress_candidates(saves: Iterable[SaveEvent], started_at_unix: float, session_end_seconds: float) -> list[Candidate]:
    out: list[Candidate] = []
    for s in saves:
        t = s.t_unix - started_at_unix
        if t < 0 or t > session_end_seconds:
            continue
        a = max(0.0, t - 5.0)
        b = min(session_end_seconds, t + 5.0)
        if b > a:
            out.append(Candidate(start=a, end=b, category="progress", confidence=0.9, evidence=s.path))
    return out


def speech_candidates(segments: Iterable[TranscriptSegment]) -> list[Candidate]:
    out: list[Candidate] = []
    for seg in segments:
        dur = seg.end_seconds - seg.start_seconds
        if dur < 1.0 or dur > 60.0:
            continue
        if len(seg.text.split()) < 3:
            continue
        out.append(Candidate(
            start=seg.start_seconds, end=seg.end_seconds,
            category="speech", confidence=0.7, evidence=seg.text[:200],
        ))
    return out


def _is_reference(cls: str, title: str) -> bool:
    if _REFERENCE_CLASS_RE.match(cls):
        return True
    # Even if the class isn't a known browser, treat docs sites in title as research.
    return bool(re.search(r"(stack ?overflow|docs?\.|mdn|github\.com|reddit|wiki|tutorial)", title, re.IGNORECASE))


def _is_editor(cls: str) -> bool:
    return bool(_EDITOR_CLASS_RE.match(cls))


def research_candidates(windows: list[WindowEvent], started_at_unix: float, session_end_seconds: float) -> list[Candidate]:
    """Detect contiguous spans (>=15s) of reference foreground window."""
    if not windows:
        return []
    out: list[Candidate] = []
    # Window events are sparse (only on change). Treat each event as the start
    # of a state that persists until the next event or session end.
    sorted_ws = sorted(windows, key=lambda w: w.t_unix)
    for w, nxt in zip(sorted_ws, sorted_ws[1:] + [None]):
        if not _is_reference(w.cls, w.title) or _is_editor(w.cls):
            continue
        t0 = w.t_unix - started_at_unix
        t1 = (nxt.t_unix - started_at_unix) if nxt else session_end_seconds
        a = max(0.0, t0)
        b = min(session_end_seconds, t1)
        if b - a < 15.0:
            continue
        out.append(Candidate(
            start=a, end=b, category="research", confidence=0.6,
            evidence=f"{w.cls}: {w.title}"[:200],
        ))
    return out


def stuck_candidates(
    segments: list[TranscriptSegment],
    saves: list[SaveEvent],
    started_at_unix: float,
    session_end_seconds: float,
) -> list[Candidate]:
    """Contiguous interval >=90s with no save event AND >=1 uncertainty segment."""
    save_offsets = sorted(s.t_unix - started_at_unix for s in saves)
    save_offsets = [s for s in save_offsets if 0 <= s <= session_end_seconds]
    boundaries = [0.0, *save_offsets, session_end_seconds]

    # Build no-save intervals between consecutive save events.
    intervals: list[tuple[float, float]] = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b - a >= 90.0:
            intervals.append((a, min(b, a + 1800.0)))  # cap at 1800s per R3.3

    if not intervals:
        return []

    out: list[Candidate] = []
    for a, b in intervals:
        # Find uncertainty segment overlapping [a, b].
        overlap = [s for s in segments if _UNCERTAIN_RE.search(s.text) and s.end_seconds > a and s.start_seconds < b]
        if not overlap:
            continue
        evidence = overlap[0].text[:200]
        out.append(Candidate(start=a, end=b, category="stuck", confidence=0.7, evidence=evidence))
    return out
