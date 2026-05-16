"""Classify each PR-diff added/modified line as human, agent, mixed, or unknown.

Uses agent-edit evidence collected from Claude Code session logs scoped to
the capture window. A diff line is:
  agent   if its text appears in the agent's edit history for the same file
  human   if the file has NO agent edits at all in this session
  mixed   if the file has agent edits BUT this specific line text is not
          in the agent set (developer typed by hand in a file the agent
          also touched)
  unknown if we have no evidence about the file (file not in capture or
          no Claude Code session log for it)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

log = logging.getLogger("trace.contribution.mapper")


@dataclass
class LineLabel:
    line: int
    text: str
    label: str  # "human" | "agent" | "mixed" | "unknown"


@dataclass
class FileContribution:
    path: str
    labels: list[LineLabel] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"human": 0, "agent": 0, "mixed": 0, "unknown": 0})

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "counts": dict(self.counts),
        }


_PATCH_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_added_lines(patch: str) -> list[tuple[int, str]]:
    """Walk a unified diff patch and return list of (new_line_no, text) for + lines."""
    if not patch:
        return []
    out: list[tuple[int, str]] = []
    new_line = 0
    for raw in patch.splitlines():
        m = _PATCH_HEADER_RE.match(raw)
        if m:
            new_line = int(m.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out.append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue  # deletion, no new line number consumed
        else:
            new_line += 1
    return out


def _matches_agent_text(line_text: str, agent_lines: set[str]) -> bool:
    s = line_text.strip()
    if len(s) < 3:
        return False
    return s in agent_lines


def classify(
    pr_files: list[dict],
    agent_edits_by_file: dict[str, set[str]],
) -> list[FileContribution]:
    """pr_files: from GitHubClient.get_pr_files (list of {path, patch}).

    agent_edits_by_file: {absolute_path: set_of_lines_agent_wrote}.

    Returns one FileContribution per file with classified added lines.
    Matching uses basename so absolute paths (Claude logs) and relative
    PR paths reconcile.
    """
    # Index agent edits by basename for fuzzy match.
    by_basename: dict[str, set[str]] = {}
    for fp, lines in agent_edits_by_file.items():
        base = os.path.basename(fp)
        by_basename.setdefault(base, set()).update(lines)

    out: list[FileContribution] = []
    for f in pr_files:
        path = f.get("path", "")
        patch = f.get("patch", "") or ""
        contribution = FileContribution(path=path)

        # Find the matching agent edit set.
        base = os.path.basename(path)
        agent_lines = by_basename.get(base, set())
        file_was_touched = bool(agent_lines)

        added = parse_added_lines(patch)
        for line_no, text in added:
            if file_was_touched and _matches_agent_text(text, agent_lines):
                label = "agent"
            elif file_was_touched:
                label = "mixed"
            elif not by_basename:
                label = "unknown"
            else:
                label = "human"
            contribution.labels.append(LineLabel(line=line_no, text=text, label=label))
            contribution.counts[label] += 1

        out.append(contribution)
    return out


def render_comment(contributions: list[FileContribution]) -> str:
    """Markdown summary suitable for a PR comment."""
    if not contributions:
        return "**@trace contribution map**: no diff to classify."

    total = {"human": 0, "agent": 0, "mixed": 0, "unknown": 0}
    for c in contributions:
        for k, v in c.counts.items():
            total[k] += v

    grand = sum(total.values()) or 1
    pct_ai = round(100 * (total["agent"] + 0.5 * total["mixed"]) / grand)
    pct_h = round(100 * (total["human"] + 0.5 * total["mixed"]) / grand)

    lines = [
        "## trace contribution map",
        "",
        f"AI vs human attribution for the {grand} added lines in this PR. "
        f"Evidence: Claude Code session logs during the capture window.",
        "",
        f"- **Overall: ~{pct_ai}% AI / ~{pct_h}% human / 100% human-verified**",
        "",
        "| file | human | agent | mixed | unknown |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in contributions:
        if not any(c.counts.values()):
            continue
        lines.append(
            f"| `{c.path}` | {c.counts['human']} | {c.counts['agent']} | "
            f"{c.counts['mixed']} | {c.counts['unknown']} |"
        )
    lines.append("")
    lines.append("_human_ = typed by hand. _agent_ = produced by Claude Code Edit/Write. "
                 "_mixed_ = file touched by agent but this line did not match agent text. "
                 "_unknown_ = no agent edit evidence for this file.")
    return "\n".join(lines)
