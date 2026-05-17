"""Classify each PR-diff file as human, agent, mixed, or unknown.

Evidence comes from trace's own session capture (scenes + transcript + timeline).
No external tool dependency.

  agent   = file saved while AI-assistant screen/speech signal active
  human   = file saved during session, no AI signal detected
  mixed   = file has partial AI signal (some saves in AI window, some not)
  unknown = file not saved at all during session (added outside capture window)
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
    saved_files: set[str] | None = None,
) -> list[FileContribution]:
    """pr_files: from GitHubClient.get_pr_files (list of {path, patch}).

    agent_edits_by_file: {rel_or_abs_path: {"__agent__"}} from scanner.
    saved_files: set of rel paths saved during session (for human vs unknown).

    File-level classification (all added lines in a file get the same label):
      agent   = file in agent_edits_by_file
      human   = file in saved_files but NOT in agent_edits_by_file
      unknown = file not in saved_files at all
    """
    # Normalise to basenames for matching.
    agent_basenames: set[str] = {os.path.basename(fp) for fp in agent_edits_by_file}
    saved_basenames: set[str] = {os.path.basename(fp) for fp in (saved_files or set())}
    any_session_evidence = bool(saved_basenames or agent_basenames)

    out: list[FileContribution] = []
    for f in pr_files:
        path = f.get("path", "")
        patch = f.get("patch", "") or ""
        contribution = FileContribution(path=path)
        base = os.path.basename(path)

        # Check for mixed sentinel first (both human and agent saves observed).
        agent_val = next((v for k, v in agent_edits_by_file.items() if os.path.basename(k) == base), None)
        mixed_ratio: float | None = None  # agent fraction of saves, None if not mixed
        if agent_val and agent_val != {"__agent__"}:
            sentinel = next(iter(agent_val), "")
            if sentinel.startswith("__mixed__"):
                try:
                    frac_str = sentinel[len("__mixed__"):]  # "1/2"
                    num, den = frac_str.split("/")
                    mixed_ratio = int(num) / int(den)
                except Exception:
                    mixed_ratio = 0.5
                file_label = "mixed"
            else:
                file_label = "agent"
        elif base in agent_basenames:
            file_label = "agent"
        elif base in saved_basenames:
            file_label = "human"
        else:
            file_label = "unknown"

        added = parse_added_lines(patch)
        n_lines = len(added)
        if file_label == "mixed" and mixed_ratio is not None and n_lines > 0:
            # Split lines proportionally by save ratio instead of 50/50.
            agent_lines = round(n_lines * mixed_ratio)
            human_lines = n_lines - agent_lines
            contribution.counts["agent"] += agent_lines
            contribution.counts["human"] += human_lines
            for line_no, text in added:
                contribution.labels.append(LineLabel(line=line_no, text=text, label="mixed"))
        else:
            for line_no, text in added:
                contribution.labels.append(LineLabel(line=line_no, text=text, label=file_label))
                contribution.counts[file_label] += 1

        out.append(contribution)
    return out


def render_comment(contributions: list[FileContribution]) -> str:
    """Markdown summary suitable for a PR comment."""
    if not contributions:
        return "**trace contribution map**: no diff to classify."

    total = {"human": 0, "agent": 0, "mixed": 0, "unknown": 0}
    for c in contributions:
        for k, v in c.counts.items():
            total[k] += v

    grand = sum(total.values()) or 1
    observed = grand - total["unknown"]
    obs_denom = observed or 1
    pct_ai = round(100 * (total["agent"] + 0.5 * total["mixed"]) / obs_denom)
    pct_h = round(100 * (total["human"] + 0.5 * total["mixed"]) / obs_denom)
    pct_unk = round(100 * total["unknown"] / grand)

    lines = [
        "## trace contribution map",
        "",
        f"AI vs human attribution for the {grand} added lines in this PR. "
        f"Evidence: screen activity, voice transcript, and scene labels from the recorded session.",
        "",
        f"**Overall: ~{pct_ai}% AI / ~{pct_h}% human** (of {observed} observed lines; {pct_unk}% not captured in session)",
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
    lines.append(
        "_agent_ = file saved while AI assistant on screen or invoked by voice. "
        "_human_ = file saved during session, no AI signal. "
        "_unknown_ = file not written during capture window (added outside session or by CI)."
    )
    return "\n".join(lines)
