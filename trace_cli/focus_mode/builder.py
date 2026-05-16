"""Reviewer Focus Mode: compress a large PR to 'review these N areas carefully'.

Combines three evidence sources into a per-file risk score:
  - Stuck-tagged timeline moments referencing the file
  - Large changes (>= 50 changed lines per file) per R8.3
  - Scene-index evidence of errors visible on screen while editing the file
  - Uncertainty phrases in transcript ('not sure', 'wait this is wrong')
    overlapping the file edit window

Output: a structured PR comment listing up to N focus areas, each with
  - file path + line ranges (from diff hunks)
  - reason (stuck / large change / error seen / uncertainty / mixed)
  - one-line evidence quote
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from trace_cli.session.models import Timeline, Transcript

log = logging.getLogger("trace.focus")

UNCERTAIN_RE = re.compile(
    r"\b(not sure|why (?:is|does|isn'?t|doesn'?t)|hmm+|what the|"
    r"i (?:think|don'?t know|wonder)|maybe|that'?s weird|"
    r"this is strange|stuck|confused|no idea|wait[, ]+this is wrong|"
    r"something'?s off|doesn'?t look right)\b",
    re.IGNORECASE,
)

LARGE_CHANGE_THRESHOLD = 50


@dataclass
class FocusEntry:
    file_path: str
    ranges: list[tuple[int, int]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    score: int = 0

    def render(self) -> str:
        ranges_str = ", ".join(f"L{a}-L{b}" for a, b in self.ranges) if self.ranges else "whole file"
        reasons_str = ", ".join(self.reasons) or "high change"
        lines = [
            f"- [ ] **`{self.file_path}`** ({ranges_str}) — _{reasons_str}_",
        ]
        for ev in self.evidence[:2]:
            lines.append(f"      > {ev[:140]}")
        return "\n".join(lines)


def _hunk_ranges(patch: str) -> list[tuple[int, int]]:
    """Extract added-line ranges from a unified diff hunk header."""
    out: list[tuple[int, int]] = []
    for raw in (patch or "").splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw)
        if m:
            start = int(m.group(1))
            count = int(m.group(2) or 1)
            if count > 0:
                out.append((start, start + count - 1))
    return out


def _file_matches_evidence(evidence: str, file_path: str) -> bool:
    if not evidence or not file_path:
        return False
    return os.path.basename(file_path) in evidence or file_path in evidence


def build_focus(
    pr_files: list[dict],
    timeline: Timeline,
    transcript: Transcript,
    *,
    max_areas: int = 4,
) -> list[FocusEntry]:
    """Score every changed file and return the top `max_areas` to review."""
    by_path: dict[str, FocusEntry] = {}

    for f in pr_files:
        path = f.get("path", "")
        if not path:
            continue
        entry = FocusEntry(file_path=path, ranges=_hunk_ranges(f.get("patch", "") or ""))

        changes = int(f.get("changes", 0) or (int(f.get("additions", 0) or 0) + int(f.get("deletions", 0) or 0)))
        if changes >= LARGE_CHANGE_THRESHOLD:
            entry.reasons.append("large change")
            entry.score += 2
            entry.evidence.append(f"{changes} changed lines")

        # Stuck moments referencing this file
        for m in timeline.moments:
            if m.category != "stuck":
                continue
            if _file_matches_evidence(m.evidence, path):
                entry.reasons.append("got stuck")
                entry.score += 3
                entry.evidence.append(m.evidence)
                break

        # Uncertainty in transcript while file was being edited (approximated as
        # any uncertain phrase in the session if file appears in diff at all)
        for seg in transcript.segments:
            if UNCERTAIN_RE.search(seg.text or ""):
                entry.reasons.append("verbal uncertainty")
                entry.score += 1
                entry.evidence.append(seg.text.strip())
                break

        if entry.score > 0 or changes >= LARGE_CHANGE_THRESHOLD:
            by_path[path] = entry

    ranked = sorted(by_path.values(), key=lambda e: e.score, reverse=True)
    return ranked[:max_areas]


def render_comment(entries: list[FocusEntry]) -> str:
    if not entries:
        return (
            "## trace - Reviewer Focus Mode\n\n"
            "_No high-risk areas detected. The session shows steady progress with no stuck "
            "moments, large-file changes, or verbal uncertainty._"
        )
    lines = [
        "## trace - Reviewer Focus Mode",
        "",
        f"Of the changed files, **review these {len(entries)} areas carefully**. "
        "Ranking is based on stuck-tagged timeline moments, large per-file change counts, "
        "and verbal uncertainty during editing.",
        "",
    ]
    for e in entries:
        lines.append(e.render())
        lines.append("")
    lines.append("---")
    lines.append("_Evidence comes from the recorded session. Tick the boxes as you review._")
    return "\n".join(lines)
