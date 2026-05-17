"""Clip selector: build a narrative-covering clip list from timeline moments.

Selection philosophy:
  - Always include research windows (docs reading).
  - Include speech moments that explain AI invocations or bugs — these are
    the most interesting narrative beats.
  - Include progress clips only for real code files (not .git/objects,
    .pytest_cache, __pycache__ etc.).
  - Budget remaining slots with diversity across the session timeline.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from trace_cli.session.models import Timeline

log = logging.getLogger("trace.pr_video.selector")

# Paths that are generated artifacts — not meaningful code edits.
_JUNK_PATH_PATTERNS = re.compile(
    r"(\.pytest_cache|__pycache__|\.git/objects|\.git/COMMIT_EDITMSG"
    r"|\.git/logs|\.git/refs|\.git/index|\.pyc$|\.egg-info|node_modules"
    r"|/tmp_obj_|\.lock$|dist-info)"
)

# Speech evidence containing AI invocation signals.
_AI_INVOKE_RE = re.compile(
    r"\b(claude|copilot|chatgpt|gpt|cursor|let it|have it|ask it|told him|"
    r"tell claude|ask claude|claude is|it is adding|it is writing|claude (fixed|did|added))\b",
    re.IGNORECASE,
)

# Speech evidence describing bugs/errors/stuck moments.
_BUG_RE = re.compile(
    r"\b(error|bug|crash|exception|fail|broken|key error|assert|traceback|"
    r"wrong|incorrect|not working|fix|fallback)\b",
    re.IGNORECASE,
)


@dataclass
class Clip:
    """One narratable moment."""
    start: float
    end: float
    file_path: str | None
    category: str
    evidence: str
    spoken: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


class InsufficientContent(Exception):
    pass


def _is_junk_path(path: str) -> bool:
    return bool(_JUNK_PATH_PATTERNS.search(path))


def _path_matches_diff(evidence_path: str, diff_paths: set[str]) -> str | None:
    if not evidence_path or _is_junk_path(evidence_path):
        return None
    base = os.path.basename(evidence_path)
    for dp in diff_paths:
        if dp == evidence_path or os.path.basename(dp) == base:
            return dp
    return None


def select_clips(
    timeline: Timeline,
    diff_files: list[str],
    *,
    min_total: float = 10.0,
    max_total: float = 142.0,
    max_clips: int = 14,
    pad_seconds: float = 2.0,
    min_clip_seconds: float = 3.0,
    max_clip_seconds: float = 12.0,
    max_research_seconds: float = 15.0,
) -> list[Clip]:
    """Pick narrative-covering clips ordered by start time.

    Priority tiers:
      1. research moments (always include — shows docs/browser reading)
      2. speech with AI invocation signal (developer talking to Claude/Copilot)
      3. speech with bug/error signal (describing problem being fixed)
      4. progress on real diff files (code editing visible on screen)
      5. other substantial speech (context/explanation)
      6. progress on non-diff-matched real files
    """
    diff_set = set(diff_files)
    end_s = timeline.session_end_seconds

    def _make_clip(m, override_cat=None, cap: float | None = None) -> Clip:
        cat = override_cat or m.category
        start = max(0.0, m.start_seconds - pad_seconds)
        end = min(end_s, m.end_seconds + pad_seconds)
        dur = end - start
        if dur < min_clip_seconds:
            need = min_clip_seconds - dur
            end = min(end_s, end + need)
            if (end - start) < min_clip_seconds:
                start = max(0.0, start - (min_clip_seconds - (end - start)))
        clip_cap = cap if cap is not None else max_clip_seconds
        if (end - start) > clip_cap:
            end = start + clip_cap
        fp = _path_matches_diff(m.evidence, diff_set) if cat == "progress" else None
        return Clip(
            start=start, end=end,
            file_path=fp,
            category=cat,
            evidence=m.evidence,
            spoken=m.evidence if cat in ("speech", "research") else "",
        )

    # Build candidate pools by tier.
    tier_research: list[Clip] = []
    tier_ai_speech: list[Clip] = []
    tier_bug_speech: list[Clip] = []
    tier_progress_diff: list[Clip] = []
    tier_speech_other: list[Clip] = []
    tier_progress_other: list[Clip] = []
    tier_intro_speech: list[Clip] = []  # first meaningful speech = session intro

    for m in timeline.moments:
        if m.confidence == 0.0 and m.category == "progress":
            continue  # gap-fill markers

        if m.category == "research":
            # Cap research clips so they don't eat the whole budget.
            c = _make_clip(m, cap=max_research_seconds)
            if c.duration >= min_clip_seconds * 0.5:
                tier_research.append(c)

        elif m.category == "speech":
            ev = m.evidence or ""
            c = _make_clip(m)
            if c.duration < min_clip_seconds * 0.5:
                continue
            if _AI_INVOKE_RE.search(ev):
                tier_ai_speech.append(c)
            elif _BUG_RE.search(ev):
                tier_bug_speech.append(c)
            elif len(ev) > 20:
                # First speech moment in session = intro.
                if not tier_intro_speech and m.start_seconds < end_s * 0.15:
                    tier_intro_speech.append(c)
                else:
                    tier_speech_other.append(c)

        elif m.category == "progress":
            if _is_junk_path(m.evidence):
                continue  # skip .git/objects, .pytest_cache etc.
            c = _make_clip(m)
            if c.duration < min_clip_seconds * 0.5:
                continue
            if c.file_path:
                tier_progress_diff.append(c)
            else:
                tier_progress_other.append(c)

        elif m.category == "stuck":
            # treat stuck like high-priority speech
            c = _make_clip(m)
            if c.duration >= min_clip_seconds * 0.5:
                tier_bug_speech.append(c)

    log.info(
        "candidate tiers: intro=%d research=%d ai_speech=%d bug_speech=%d progress_diff=%d speech_other=%d",
        len(tier_intro_speech), len(tier_research), len(tier_ai_speech),
        len(tier_bug_speech), len(tier_progress_diff), len(tier_speech_other),
    )

    # Merge overlapping clips within each tier (same category, overlapping spans).
    def _merge(clips: list[Clip]) -> list[Clip]:
        clips = sorted(clips, key=lambda c: c.start)
        out: list[Clip] = []
        for c in clips:
            if out and out[-1].end >= c.start:
                out[-1].end = max(out[-1].end, c.end)
                if not out[-1].file_path:
                    out[-1].file_path = c.file_path
                ev2 = c.evidence
                if ev2 and ev2 not in out[-1].evidence:
                    out[-1].evidence = (out[-1].evidence + " | " + ev2)[:300]
            else:
                out.append(c)
        return out

    tier_intro_speech = _merge(tier_intro_speech)
    tier_research = _merge(tier_research)
    tier_ai_speech = _merge(tier_ai_speech)
    tier_bug_speech = _merge(tier_bug_speech)
    tier_progress_diff = _merge(tier_progress_diff)
    tier_speech_other = _merge(tier_speech_other)
    tier_progress_other = _merge(tier_progress_other)

    # Greedy selection: fill budget in priority order, ensuring temporal diversity.
    chosen: list[Clip] = []
    total = 0.0

    chosen_ids: set[int] = set()

    def _add(candidates: list[Clip], limit: int | None = None) -> None:
        nonlocal total
        added = 0
        for c in candidates:
            if id(c) in chosen_ids:
                continue
            if total + c.duration > max_total:
                continue
            if len(chosen) >= max_clips:
                break
            if limit is not None and added >= limit:
                break
            chosen.append(c)
            chosen_ids.add(id(c))
            total += c.duration
            added += 1

    # Session intro — first speech moment sets the scene.
    _add(tier_intro_speech, limit=1)

    # Research (docs reading) — capped clip, always include.
    _add(tier_research)

    # Code edits on real diff files — one clip per unique file for variety,
    # then allow one more per file if budget remains.
    seen_files: set[str] = set()
    first_per_file: list[Clip] = []
    extras: list[Clip] = []
    for c in tier_progress_diff:
        fp = c.file_path or ""
        if fp not in seen_files:
            seen_files.add(fp)
            first_per_file.append(c)
        else:
            extras.append(c)
    _add(first_per_file)           # one per unique file first
    _add(extras, limit=1)          # allow one repeat if budget allows

    # AI invocation speech — up to 4 (core demo: developer + Claude).
    _add(tier_ai_speech, limit=4)

    # Bug/error speech — up to 3 (problem + fix arc).
    _add(tier_bug_speech, limit=3)

    # More code edits if budget allows.
    _add(tier_progress_diff, limit=2)

    # Explanatory speech for context.
    _add(tier_speech_other, limit=2)

    # Non-diff progress — remaining budget.
    _add(tier_progress_other, limit=1)

    if total < min_total:
        if end_s < min_total:
            return [Clip(start=0.0, end=end_s, file_path=None, category="progress", evidence="full session")]
        raise InsufficientContent(
            f"selected {total:.1f}s of clips, need >= {min_total}s "
            f"(research={len(tier_research)} ai_speech={len(tier_ai_speech)} "
            f"bug={len(tier_bug_speech)} progress={len(tier_progress_diff)})"
        )

    # Sort chronologically for the final video.
    chosen.sort(key=lambda c: c.start)

    # Drop any clips that got squashed too short (shouldn't happen but guard).
    chosen = [c for c in chosen if (c.end - c.start) >= min_clip_seconds * 0.5]
    # Sort chronologically — source overlaps are fine, render places them sequentially.
    chosen.sort(key=lambda c: c.start)

    log.info(
        "selected %d clips totaling %.1fs: %s",
        len(chosen), sum(c.duration for c in chosen),
        [(c.category, f"{c.start:.0f}-{c.end:.0f}s") for c in chosen],
    )
    return chosen
