"""Timeline_Builder. Merges classifier candidates into a gap-free timeline.

Priority on overlap: progress > stuck > research > speech (R3.10).
Gap fill: progress with confidence 0.0 (R3.11).
Coverage: [0, session_end] contiguous (R3.1).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from trace_cli.session.models import TaggedMoment, Timeline

log = logging.getLogger("trace.timeline")

PRIORITY: dict[str, int] = {"progress": 4, "stuck": 3, "research": 2, "speech": 1}


@dataclass
class Candidate:
    start: float
    end: float
    category: str
    confidence: float
    evidence: str

    def to_moment(self) -> TaggedMoment:
        return TaggedMoment(
            start_seconds=self.start,
            end_seconds=self.end,
            category=self.category,  # type: ignore[arg-type]
            confidence=self.confidence,
            evidence=self.evidence,
        )


def _clip(start: float, end: float, lo: float, hi: float) -> tuple[float, float] | None:
    a = max(start, lo)
    b = min(end, hi)
    if b <= a:
        return None
    return a, b


def merge(
    candidates: Iterable[Candidate],
    *,
    session_end_seconds: float,
    session_id: str,
) -> Timeline:
    """Boundary sweep. For each (a,b) interval, pick highest-priority covering candidate."""
    cands = [c for c in candidates if c.end > c.start and c.start < session_end_seconds]
    # Clip to bounds
    cands = [Candidate(*p, c.category, c.confidence, c.evidence) for c in cands
             if (p := _clip(c.start, c.end, 0.0, session_end_seconds))]

    boundaries: set[float] = {0.0, session_end_seconds}
    for c in cands:
        boundaries.add(c.start)
        boundaries.add(c.end)
    pts = sorted(b for b in boundaries if 0.0 <= b <= session_end_seconds)
    if not pts or pts[0] > 0.0:
        pts = [0.0, *pts]
    if pts[-1] < session_end_seconds:
        pts.append(session_end_seconds)

    moments: list[TaggedMoment] = []
    for a, b in zip(pts, pts[1:]):
        if b <= a:
            continue
        # Pick covering candidate with highest priority; tie-break by confidence desc.
        best: Candidate | None = None
        for c in cands:
            if c.start <= a and c.end >= b:
                if (
                    best is None
                    or PRIORITY[c.category] > PRIORITY[best.category]
                    or (PRIORITY[c.category] == PRIORITY[best.category] and c.confidence > best.confidence)
                ):
                    best = c
        if best is None:
            moments.append(TaggedMoment(
                start_seconds=a, end_seconds=b, category="progress", confidence=0.0, evidence=""
            ))
        else:
            moments.append(TaggedMoment(
                start_seconds=a, end_seconds=b, category=best.category,  # type: ignore[arg-type]
                confidence=best.confidence, evidence=best.evidence,
            ))

    # Coalesce adjacent moments sharing (category, evidence).
    coalesced: list[TaggedMoment] = []
    for m in moments:
        if coalesced:
            last = coalesced[-1]
            if last.category == m.category and last.evidence == m.evidence and last.end_seconds == m.start_seconds:
                coalesced[-1] = TaggedMoment(
                    start_seconds=last.start_seconds,
                    end_seconds=m.end_seconds,
                    category=last.category,
                    confidence=max(last.confidence, m.confidence),
                    evidence=last.evidence,
                )
                continue
        coalesced.append(m)

    return Timeline(session_id=session_id, session_end_seconds=session_end_seconds, moments=coalesced)


def to_json(t: Timeline) -> str:
    return t.model_dump_json(indent=2)


def from_json(raw: str) -> Timeline:
    return Timeline.model_validate_json(raw)
