"""End-to-end ship pipeline: commit + push + open PR + generate.

Flow:
  1. cd into session's project_dir
  2. git add -A; if uncommitted changes, AI-generate commit message from diff, commit
  3. push current branch (create remote tracking if missing)
  4. gh pr view to check existing PR; if missing, AI-generate title+body, gh pr create
  5. run trace generate against the PR
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from trace_cli.pr_video.generator import generate_pr_video
from trace_cli.pr_video.render import RenderResult
from trace_cli.session.models import Transcript
from trace_cli.session.store import SessionStore
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.ship")


class ShipError(Exception):
    pass


@dataclass
class ShipResult:
    pr_url: str
    branch: str
    commit_sha: str | None
    render: RenderResult


def _run(cmd: list[str], *, cwd: Path, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    log.debug("$ %s (cwd=%s)", " ".join(cmd), cwd)
    r = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        raise ShipError(f"{' '.join(cmd)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r


def _current_branch(repo: Path) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()


def _has_uncommitted(repo: Path) -> bool:
    r = _run(["git", "status", "--porcelain"], cwd=repo)
    return bool(r.stdout.strip())


def _has_unpushed(repo: Path, branch: str) -> bool:
    upstream = _run(
        ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
        cwd=repo, check=False,
    )
    if upstream.returncode != 0:
        return True
    r = _run(["git", "log", "@{u}..HEAD", "--oneline"], cwd=repo)
    return bool(r.stdout.strip())


def _diff_summary(repo: Path) -> str:
    """Combined: staged + unstaged + uncommitted file list."""
    parts = []
    for cmd in (["git", "diff", "--stat", "HEAD"], ["git", "diff", "--cached", "--stat"]):
        r = _run(cmd, cwd=repo, check=False)
        if r.stdout.strip():
            parts.append(r.stdout.strip())
    return "\n".join(parts)[:3000]


def _transcript_text(store: SessionStore, session_id: str, *, limit: int = 4000) -> str:
    p = store.transcript_path(session_id)
    if not p.exists():
        return ""
    try:
        tr = Transcript.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    text = " ".join(seg.text.strip() for seg in tr.segments if seg.text.strip())
    return text[:limit]


def _gen_commit_message(client: VideoDBClient, diff: str, transcript: str) -> str:
    prompt = (
        "Write a single git commit message subject line (max 60 chars, imperative mood, "
        "no period at end) summarizing this change. No body, just one line.\n\n"
        f"Diff:\n{diff[:1500]}\n\n"
        f"Developer transcript (for intent):\n{transcript[:1500]}\n\n"
        "Output only the subject line."
    )
    try:
        msg = client.generate_text(prompt=prompt, model="pro").strip()
        msg = msg.splitlines()[0].strip().strip('"').strip("'")
        if len(msg) > 70:
            msg = msg[:67] + "..."
        return msg or "trace session changes"
    except Exception as e:  # noqa: BLE001
        log.warning("commit message gen failed (%s); using fallback", e)
        return "trace session changes"


def _gen_pr_text(client: VideoDBClient, diff: str, transcript: str, commits: str) -> tuple[str, str]:
    """Returns (title, body). Title <= 70 chars, body markdown."""
    prompt = (
        "Generate a GitHub PR title and body for the following work. Return strict JSON:\n"
        '{"title": "...", "body": "..."}\n\n'
        "Title: imperative mood, max 70 chars, no period.\n"
        "Body: 2-4 short paragraphs in markdown. Speak in first person. Stay faithful to the "
        "transcript and diff; do not invent claims.\n\n"
        f"Commits in this branch:\n{commits[:1500]}\n\n"
        f"Diff stat:\n{diff[:1500]}\n\n"
        f"Developer transcript:\n{transcript[:2500]}\n\n"
        "Output JSON only."
    )
    try:
        raw = client.generate_text(prompt=prompt, model="pro").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
        title = str(data.get("title", "")).strip()[:70] or "Session changes"
        body = str(data.get("body", "")).strip() or "_See trace walkthrough below._"
        return title, body
    except Exception as e:  # noqa: BLE001
        log.warning("PR text gen failed (%s); using fallback", e)
        return ("Session changes", "_See trace walkthrough below._")


def _gh_pr_view(repo: Path, branch: str) -> str | None:
    r = _run(
        ["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
        cwd=repo, check=False,
    )
    if r.returncode == 0:
        url = r.stdout.strip()
        return url or None
    return None


def _gh_pr_create(repo: Path, *, title: str, body: str, base: str) -> str:
    r = _run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
        cwd=repo,
    )
    out = r.stdout.strip().splitlines()
    for line in reversed(out):
        if line.startswith("https://github.com/"):
            return line
    raise ShipError(f"could not parse PR URL from gh output: {r.stdout!r}")


def _default_base_branch(repo: Path) -> str:
    r = _run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo, check=False,
    )
    if r.returncode == 0:
        ref = r.stdout.strip()  # refs/remotes/origin/main
        return ref.rsplit("/", 1)[-1] or "main"
    return "main"


def ship(
    session_id: str,
    *,
    base: str | None = None,
    auto_commit: bool = True,
    repo_override: Path | None = None,
) -> ShipResult:
    """End-to-end: commit + push + open PR + generate. Idempotent on re-run.

    If repo_override is given, that directory is used instead of the session's
    recorded project_dir (useful when the session was recorded in a repo with
    no remote — pick a different repo to ship the PR to).
    """
    store = SessionStore()
    meta = store.read_metadata(session_id)
    repo = repo_override or (Path(meta.project_dir) if meta.project_dir else None)
    if repo is None:
        raise ShipError(f"session {session_id} has no project_dir; pass --repo")
    if not (repo / ".git").exists():
        raise ShipError(f"{repo} is not a git repo")

    branch = _current_branch(repo)
    base = base or _default_base_branch(repo)
    if branch in ("main", "master", base):
        # Auto-create a feature branch off the current HEAD so we never push
        # session-time dirty changes directly to main.
        from datetime import datetime
        new_branch = f"trace/session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        log.info("on protected branch %r; creating feature branch %s", branch, new_branch)
        _run(["git", "checkout", "-b", new_branch], cwd=repo)
        branch = new_branch


    log.info("ship: repo=%s branch=%s base=%s", repo, branch, base)

    client = VideoDBClient()
    transcript = _transcript_text(store, session_id)
    commit_sha: str | None = None

    # 1. Commit if dirty
    if _has_uncommitted(repo):
        if not auto_commit:
            raise ShipError("uncommitted changes present and --no-commit set")
        diff = _diff_summary(repo)
        msg = _gen_commit_message(client, diff, transcript)
        log.info("auto-commit: %s", msg)
        _run(["git", "add", "-A"], cwd=repo)
        _run(
            [
                "git",
                "-c", "user.email=trace@local",
                "-c", "user.name=trace ship",
                "commit", "-m", msg,
            ],
            cwd=repo,
        )
        commit_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()

    # 2. Push if unpushed
    if _has_unpushed(repo, branch):
        log.info("pushing %s -> origin", branch)
        _run(["git", "push", "-u", "origin", branch], cwd=repo)

    # 3. Find or create PR
    pr_url = _gh_pr_view(repo, branch)
    if not pr_url:
        commits_log = _run(
            ["git", "log", f"origin/{base}..HEAD", "--pretty=%s"],
            cwd=repo, check=False,
        ).stdout.strip()
        diff = _diff_summary(repo) or _run(
            ["git", "diff", f"origin/{base}..HEAD", "--stat"],
            cwd=repo, check=False,
        ).stdout.strip()
        title, body = _gen_pr_text(client, diff, transcript, commits_log)
        log.info("creating PR: %s", title)
        pr_url = _gh_pr_create(repo, title=title, body=body, base=base)
    else:
        log.info("reusing existing PR: %s", pr_url)

    # 4. Run full generate pipeline
    log.info("running generate against %s", pr_url)
    render = generate_pr_video(session_id, pr_url, dry_run=False)

    return ShipResult(pr_url=pr_url, branch=branch, commit_sha=commit_sha, render=render)
