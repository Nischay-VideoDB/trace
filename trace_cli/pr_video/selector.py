"""Clip selector for PR video assembly (R4.1, R4.2, R4.9)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from trace_cli.session.models import Timeline

log = logging.getLogger("trace.pr_video.selector")


@dataclass
class Clip:
    start: float
    end: float
    file_path: str | None
    category: str
    evidence: str

    @property
    def duration(self) -> float:
        return self.end - self.start


class InsufficientContent(Exception):
    pass


def _path_matches_diff(evidence_path: str, diff_paths: set[str]) -> str | None:
    """Match a save event path (often absolute) against diff filenames."""
    if not evidence_path:
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
    min_total: float = 30.0,
    max_total: float = 90.0,
    pad_seconds: float = 10.0,
    short_session_threshold: float = 120.0,
    speech_context_seconds: float = 10.0,
) -> list[Clip]:
    """Pick clips to cover the PR. Returns list ordered by start ascending.

    Strategy:
      0. If session is shorter than short_session_threshold seconds, return a
         single clip covering the whole session. Best narration sync for a short
         demo run; clip-stitching only kicks in for longer sessions.
      1. Primary: progress moments whose evidence path matches a diff file,
         padded by pad_seconds on both sides for editor context.
      2. Per matched save: attach overlapping speech moments within
         speech_context_seconds of the save as setup or verify context.
      3. Fallback: any progress moment, then speech moments.
      4. Trim to <= max_total seconds, descending recency, one per file when
         possible (R4.2).
      5. Raise InsufficientContent if can not reach min_total.
    """
    diff_set = set(diff_files)
    end_s = timeline.session_end_seconds

    # Short-session path: one full-session clip. Narration syncs across whole run.
    if end_s <= short_session_threshold:
        # Find primary file: most-saved diff file across progress evidence
        from collections import Counter
        save_files = Counter()
        for m in timeline.moments:
            if m.category == "progress" and m.confidence > 0:
                mp = _path_matches_diff(m.evidence, diff_set)
                if mp:
                    save_files[mp] += 1
        primary = save_files.most_common(1)[0][0] if save_files else None
        return [Clip(
            start=0.0,
            end=end_s,
            file_path=primary,
            category="progress",
            evidence=f"full session ({end_s:.0f}s)",
        )]

    matched: list[Clip] = []
    other_progress: list[Clip] = []
    speech: list[Clip] = []

    for m in timeline.moments:
        if m.confidence == 0.0 and m.category == "progress":
            # gap fill, skip
            continue
        clip = Clip(
            start=max(0.0, m.start_seconds - pad_seconds),
            end=min(end_s, m.end_seconds + pad_seconds),
            file_path=None,
            category=m.category,
            evidence=m.evidence,
        )
        if m.category == "progress":
            mp = _path_matches_diff(m.evidence, diff_set)
            if mp:
                clip.file_path = mp
                matched.append(clip)
            else:
                other_progress.append(clip)
        elif m.category == "speech":
            speech.append(clip)

    # Attach speech context (setup + verify) around each matched save by
    # extending its start/end to swallow nearby speech moments.
    for save in matched:
        for sp in speech:
            if sp.start <= save.start and (save.start - sp.start) <= speech_context_seconds:
                save.start = sp.start
            if sp.end >= save.end and (sp.end - save.end) <= speech_context_seconds:
                save.end = sp.end

    # Descending recency, one per file first
    matched.sort(key=lambda c: c.start, reverse=True)
    chosen: list[Clip] = []
    seen_files: set[str] = set()
    total = 0.0
    for c in matched:
        if c.file_path in seen_files:
            continue
        if total + c.duration > max_total:
            continue
        chosen.append(c)
        seen_files.add(c.file_path or "")
        total += c.duration

    # Fill with remaining matched
    for c in matched:
        if c in chosen:
            continue
        if total + c.duration > max_total:
            continue
        chosen.append(c)
        total += c.duration

    # Fallback: any progress
    for c in other_progress:
        if total >= min_total or total + c.duration > max_total:
            continue
        chosen.append(c)
        total += c.duration

    # Fallback: speech
    for c in speech:
        if total >= min_total or total + c.duration > max_total:
            continue
        chosen.append(c)
        total += c.duration

    if total < min_total:
        # Final fallback: take whole session if short
        if end_s < min_total:
            # session itself shorter than min: emit single clip covering all
            return [Clip(start=0.0, end=end_s, file_path=None, category="progress", evidence="full session")]
        raise InsufficientContent(
            f"selected {total:.1f}s of clips, need >= {min_total}s "
            f"(matched={len(matched)} other={len(other_progress)} speech={len(speech)})"
        )

    chosen.sort(key=lambda c: c.start)
    return chosen
