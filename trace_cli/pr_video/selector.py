"""Clip selector. Per-moment clips for tight narration sync.

For PR video, each timeline moment that matters (progress on diff file,
significant speech, research, stuck) becomes its own clip. Each clip then
gets its own narration chunk so audio and video stay aligned.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from trace_cli.session.models import Timeline

log = logging.getLogger("trace.pr_video.selector")


@dataclass
class Clip:
    """One narratable moment. evidence_text is what we feed the LLM for narration."""
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


def _path_matches_diff(evidence_path: str, diff_paths: set[str]) -> str | None:
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
    min_total: float = 10.0,
    max_total: float = 120.0,
    max_clips: int = 12,
    pad_seconds: float = 2.0,
    min_clip_seconds: float = 3.0,
    max_clip_seconds: float = 12.0,
) -> list[Clip]:
    """Pick per-moment clips ordered by start time.

    Each non-trivial timeline moment becomes one clip:
      progress with matching diff file -> always include (priority)
      progress without match -> include if room
      speech with substantial text -> include if room (provides context)
      research -> include if room (shows what user looked up)

    Each clip padded by pad_seconds, clamped to [min_clip_seconds,
    max_clip_seconds]. Adjacent clips of the same category merge if they
    would overlap.
    """
    diff_set = set(diff_files)
    end_s = timeline.session_end_seconds

    raw: list[Clip] = []
    for m in timeline.moments:
        if m.confidence == 0.0 and m.category == "progress":
            continue  # skip gap-fill

        start = max(0.0, m.start_seconds - pad_seconds)
        end = min(end_s, m.end_seconds + pad_seconds)
        if end - start < min_clip_seconds:
            # extend to min length, prefer extending end first
            need = min_clip_seconds - (end - start)
            end = min(end_s, end + need)
            if end - start < min_clip_seconds:
                start = max(0.0, start - (min_clip_seconds - (end - start)))
        if end - start > max_clip_seconds:
            end = start + max_clip_seconds

        file_path = None
        if m.category == "progress":
            file_path = _path_matches_diff(m.evidence, diff_set)

        raw.append(Clip(
            start=start,
            end=end,
            file_path=file_path,
            category=m.category,
            evidence=m.evidence,
        ))

    # Step A: merge clips that overlap on source AND share category.
    raw.sort(key=lambda c: c.start)
    merged: list[Clip] = []
    for c in raw:
        if merged and merged[-1].end >= c.start and merged[-1].category == c.category:
            merged[-1].end = max(merged[-1].end, c.end)
            if not merged[-1].file_path:
                merged[-1].file_path = c.file_path
            if c.evidence and merged[-1].evidence != c.evidence:
                merged[-1].evidence = (merged[-1].evidence + " | " + c.evidence)[:250]
        else:
            merged.append(c)

    # Step B: drop speech clips contained inside (or mostly overlapping) a
    # progress clip. The progress clip's narration already covers the moment;
    # repeating it via the speech overlay just creates duplicate audio.
    progress_spans = [(c.start, c.end) for c in merged if c.category == "progress"]
    def _overlap(a0, a1, b0, b1) -> float:
        return max(0.0, min(a1, b1) - max(a0, b0))

    def _mostly_covered(c: Clip) -> bool:
        for ps in progress_spans:
            ov = _overlap(c.start, c.end, ps[0], ps[1])
            if ov / max(0.01, c.duration) > 0.5:
                return True
        return False

    merged = [c for c in merged if c.category != "speech" or not _mostly_covered(c)]

    # Step C: enforce no significant cross-category overlap. If two clips of
    # different categories overlap by more than overlap_tol seconds, the lower
    # priority one is shrunk so its start/end fall outside the higher's span.
    overlap_tol = 2.0
    prio = {"progress": 4, "stuck": 3, "research": 2, "speech": 1}
    merged.sort(key=lambda c: c.start)
    for i, hi in enumerate(merged):
        for lo in merged:
            if lo is hi:
                continue
            if prio[lo.category] >= prio[hi.category]:
                continue
            if _overlap(hi.start, hi.end, lo.start, lo.end) <= overlap_tol:
                continue
            # Trim lo to the largest portion outside hi.
            left = (lo.start, min(lo.end, hi.start))
            right = (max(lo.start, hi.end), lo.end)
            best = max([left, right], key=lambda p: p[1] - p[0])
            lo.start, lo.end = best
    # Drop anything that got squashed below min_clip_seconds.
    merged = [c for c in merged if (c.end - c.start) >= min_clip_seconds * 0.5]

    # Importance-weighted selection: rank everything by score then take the
    # top max_clips that fit in max_total. This handles long sessions where
    # raw chronological selection would drop late saves.
    def _score(c: Clip) -> tuple[int, int, float]:
        prio = {"progress": 5, "stuck": 4, "research": 2, "speech": 1}[c.category]
        match_bonus = 3 if c.file_path else 0
        duration_bonus = min(2, int(c.duration / 4))  # longer = a bit more important
        return (prio + match_bonus + duration_bonus, prio, -c.start)

    merged.sort(key=_score, reverse=True)
    chosen: list[Clip] = []
    total = 0.0
    for c in merged:
        if len(chosen) >= max_clips:
            break
        if total + c.duration > max_total:
            continue
        chosen.append(c)
        total += c.duration

    if total < min_total:
        if end_s < min_total:
            # tiny session: one full clip
            return [Clip(start=0.0, end=end_s, file_path=None, category="progress", evidence="full session")]
        raise InsufficientContent(
            f"selected {total:.1f}s of clips, need >= {min_total}s "
            f"(candidates after merge: {len(merged)})"
        )

    chosen.sort(key=lambda c: c.start)
    return chosen
