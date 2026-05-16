"""Scan Claude Code session logs to attribute file edits to the AI agent.

Claude Code stores per-project session logs at
~/.claude/projects/<encoded-path>/<uuid>.jsonl. Each line is a JSON event;
type='assistant' events with content[].type='tool_use' and name in
(Edit, Write, MultiEdit) carry the file edits the agent performed.

For the trace capture window [started_at, stopped_at], we collect every
agent-attributed line of text for every file the agent touched. Lines in
the final PR diff that match agent text get classified as 'agent';
file-untouched lines get 'human'; partially-overlapping files get 'mixed'
when both kinds of evidence exist on the same line.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("trace.contribution.scanner")

CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _new_text_from_tool_use(name: str, inp: dict) -> str:
    """Extract the agent-written text from a tool_use input block."""
    if name == "Write":
        return str(inp.get("content", "") or "")
    if name == "Edit":
        return str(inp.get("new_string", "") or "")
    if name == "MultiEdit":
        return "\n".join(str(e.get("new_string", "") or "") for e in (inp.get("edits") or []))
    return ""


def _candidate_log_dirs(project_dir: Path | None) -> list[Path]:
    """Return the project subdirs under CLAUDE_PROJECTS_ROOT to scan.

    Claude Code encodes absolute paths by replacing / with -. We try to match
    the project_dir exactly; if no match, fall back to scanning all dirs
    (slower but safer for symlinked / odd projects).
    """
    if not CLAUDE_PROJECTS_ROOT.exists():
        return []
    if not project_dir:
        return list(CLAUDE_PROJECTS_ROOT.iterdir())
    encoded = "-" + str(project_dir.resolve()).lstrip("/").replace("/", "-")
    target = CLAUDE_PROJECTS_ROOT / encoded
    if target.exists():
        return [target]
    return list(CLAUDE_PROJECTS_ROOT.iterdir())


def collect_agent_edits(
    project_dir: Path,
    *,
    started_at: datetime,
    stopped_at: datetime,
) -> dict[str, set[str]]:
    """Return {abs_file_path: set_of_agent_written_lines} for the capture window."""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if stopped_at.tzinfo is None:
        stopped_at = stopped_at.replace(tzinfo=timezone.utc)

    by_file: dict[str, set[str]] = defaultdict(set)
    for proj_dir in _candidate_log_dirs(project_dir):
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            # Skip files that ended before our window or started after.
            if mtime < started_at:
                continue
            try:
                with jsonl.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if evt.get("type") != "assistant":
                            continue
                        ts = _parse_iso(evt.get("timestamp", ""))
                        if ts is None or ts < started_at or ts > stopped_at:
                            continue
                        msg = evt.get("message", {})
                        for c in msg.get("content", []) or []:
                            if c.get("type") != "tool_use":
                                continue
                            if c.get("name") not in EDIT_TOOLS:
                                continue
                            inp = c.get("input") or {}
                            fp = str(inp.get("file_path") or "")
                            if not fp:
                                continue
                            text = _new_text_from_tool_use(c.get("name", ""), inp)
                            for raw in text.splitlines():
                                stripped = raw.strip()
                                if len(stripped) >= 3:  # skip empty/very short
                                    by_file[fp].add(stripped)
            except OSError as e:
                log.warning("read %s failed: %s", jsonl, e)
    return by_file
