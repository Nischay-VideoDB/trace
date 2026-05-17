"""Reviewer Q&A: parse /trace mentions on PR comments, answer with session clips.

Flow per polled comment:
  1. Extract question text after the first /trace token (R6.1).
  2. Look up session linked to PR via SessionStore.session_for_pr.
  3. Run two semantic searches against the indexed Video:
       a. spoken_word index: matches what the developer said.
       b. scene index: matches what was on screen.
     Merge hits by score, keep top 3 above threshold (R6.3, R6.4).
  4. Build a reply with text + up to 3 bounded clip URLs via
     video.generate_stream(timeline=[(start, end)]).
  5. Post the reply via GitHubClient and persist comment id in
     qa_replied.json so we never double-answer.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from trace_cli.github.client import GitHubClient
from trace_cli.session.store import SessionStore
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.qa")

MENTION_RE = re.compile(r"/trace\b\s*(.+)", re.IGNORECASE | re.DOTALL)
MAX_QUESTION_CHARS = 1000
MAX_REPLY_CHARS = 2000
RELEVANCE_THRESHOLD = 0.2
MAX_CLIPS = 3


@dataclass
class SearchHit:
    start: float
    end: float
    score: float
    text: str
    kind: str  # "spoken" or "scene"


def extract_question(body: str) -> str:
    """R6.1: take text after first /trace, strip, truncate."""
    if not body:
        return ""
    m = MENTION_RE.search(body)
    if not m:
        return ""
    return m.group(1).strip()[:MAX_QUESTION_CHARS]


def _spoken_hits(client: VideoDBClient, video, query: str) -> list[SearchHit]:
    out: list[SearchHit] = []
    try:
        sr = client.search_video_spoken(video, query, score_threshold=RELEVANCE_THRESHOLD)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "no results" in msg:
            log.info("spoken search: no results for %r", query)
        else:
            log.warning("spoken search failed: %s", e)
        return out
    shots = getattr(sr, "get_shots", lambda: [])() or []
    for sh in shots[:8]:
        text = (getattr(sh, "text", "") or "").strip()
        out.append(SearchHit(
            start=float(getattr(sh, "start", 0.0) or 0.0),
            end=float(getattr(sh, "end", 0.0) or 0.0),
            score=float(getattr(sh, "search_score", 0.0) or 0.0),
            text=text[:200],
            kind="spoken",
        ))
    return out


def _clean_scene_text(raw: str) -> str:
    """Convert raw JSON scene description to readable text."""
    import json as _json
    raw = raw.strip()
    # strip code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    try:
        obj = _json.loads(raw)
        parts: list[str] = []
        label = obj.get("label") or obj.get("category") or ""
        if label:
            parts.append(label)
        files = obj.get("files") or []
        if files:
            parts.append("editing " + ", ".join(str(f).split("/")[-1] for f in files[:3]))
        fns = obj.get("functions") or []
        if fns:
            parts.append("fn: " + ", ".join(str(f) for f in fns[:3]))
        errors = obj.get("errors") or []
        if errors:
            parts.append("errors: " + "; ".join(str(e)[:60] for e in errors[:2]))
        return ". ".join(parts) if parts else raw[:120]
    except Exception:
        return raw[:120]


def _scene_hits(client: VideoDBClient, video, query: str) -> list[SearchHit]:
    out: list[SearchHit] = []
    try:
        sr = client.search_video_scene(video, query, score_threshold=RELEVANCE_THRESHOLD)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "no results" in msg:
            log.info("scene search: no results for %r", query)
        else:
            log.warning("scene search failed: %s", e)
        return out
    shots = getattr(sr, "get_shots", lambda: [])() or []
    for sh in shots[:8]:
        raw_text = (getattr(sh, "text", "") or "").strip()
        text = _clean_scene_text(raw_text)
        out.append(SearchHit(
            start=float(getattr(sh, "start", 0.0) or 0.0),
            end=float(getattr(sh, "end", 0.0) or 0.0),
            score=float(getattr(sh, "search_score", 0.0) or 0.0),
            text=text[:200],
            kind="scene",
        ))
    return out


def _dedupe_by_window(hits: list[SearchHit], window: float = 8.0) -> list[SearchHit]:
    """Drop hits whose start is within `window` seconds of a higher-scored one."""
    kept: list[SearchHit] = []
    for h in sorted(hits, key=lambda x: x.score, reverse=True):
        if any(abs(h.start - k.start) < window for k in kept):
            continue
        kept.append(h)
    return kept


def _llm_summary(client: VideoDBClient, question: str, hits: list[SearchHit]) -> str:
    """Use VideoDB LLM to synthesize a direct answer from hit snippets."""
    context = "\n".join(
        f"[{h.start:.0f}s-{h.end:.0f}s {h.kind}] {h.text}" for h in hits
    )
    prompt = (
        f"You are a coding session assistant. "
        f"A reviewer asked: \"{question}\"\n\n"
        f"These are the most relevant moments from the session recording:\n{context}\n\n"
        f"Answer the reviewer's question in 1-2 sentences using only information from the session. "
        f"Be specific and direct. Do not mention timestamps or clip IDs."
    )
    try:
        return client.generate_text(prompt, model="basic").strip()
    except Exception:  # noqa: BLE001
        return ""


def build_reply(question: str, hits: list[SearchHit], clip_urls: list[str], summary: str = "") -> str:
    if not hits:
        return f"**trace-bot**: no matching moment found for `{question[:120]}`."

    lines = [f"**trace-bot** — _{question[:160]}_", ""]
    if summary:
        lines.append(summary)
        lines.append("")
    for h, url in zip(hits, clip_urls):
        snippet = h.text[:120].replace("\n", " ")
        ts = f"{h.start:.0f}s–{h.end:.0f}s"
        lines.append(f"**[{ts}]** {snippet}")
        lines.append(f"> {url}")
        lines.append("")
    return "\n".join(lines).rstrip()[:MAX_REPLY_CHARS]


def answer_one(
    client: VideoDBClient,
    gh: GitHubClient,
    pr_url: str,
    session_id: str,
    comment_id: int,
    question_body: str,
) -> str | None:
    """Run the QA pipeline for one comment. Returns the reply URL on success."""
    question = extract_question(question_body)
    if not question:
        return None

    store = SessionStore()
    meta = store.read_metadata(session_id)
    if not meta.video_id:
        body = "**trace-bot**: session not yet indexed; try again after `trace stop` completes."
        return gh.post_comment(pr_url, body[:MAX_REPLY_CHARS])

    video = client.get_video(meta.video_id)
    hits = _spoken_hits(client, video, question) + _scene_hits(client, video, question)
    hits = _dedupe_by_window(hits)[:MAX_CLIPS]

    clip_urls: list[str] = []
    for h in hits:
        try:
            clip_urls.append(client.video_clip_url(video, h.start, h.end))
        except Exception as e:  # noqa: BLE001
            log.warning("clip url gen failed for [%.1f-%.1f] (%s)", h.start, h.end, e)
            clip_urls.append("(clip unavailable)")

    summary = _llm_summary(client, question, hits) if hits else ""
    body = build_reply(question, hits, clip_urls, summary=summary)
    return gh.post_comment(pr_url, body)


class RepliedLog:
    """JSON file tracking comment ids we already answered, scoped per-session."""

    def __init__(self, session_id: str) -> None:
        store = SessionStore()
        self._path: Path = store.session_dir(session_id) / "qa_replied.json"
        self._ids: set[int] = set()
        if self._path.exists():
            try:
                self._ids = set(int(x) for x in json.loads(self._path.read_text()))
            except Exception:  # noqa: BLE001
                self._ids = set()

    def __contains__(self, cid: int) -> bool:
        return int(cid) in self._ids

    def add(self, cid: int) -> None:
        self._ids.add(int(cid))
        self._path.write_text(json.dumps(sorted(self._ids)), encoding="utf-8")


def poll_loop(
    pr_url: str,
    session_id: str,
    *,
    interval: float = 30.0,
    stop_after: float | None = None,
) -> None:
    """Long-running polling loop. Blocks until stop_after seconds elapsed."""
    import time

    gh = GitHubClient()
    client = VideoDBClient()
    log_done = RepliedLog(session_id)
    store = SessionStore()
    store.link_pr(pr_url, session_id)

    started = time.time()
    last_since = None
    log.info("polling %s for /trace mentions every %ds (session %s)", pr_url, interval, session_id)
    while True:
        try:
            comments = gh.list_comments(pr_url, since_iso=last_since)
        except Exception as e:  # noqa: BLE001
            log.warning("list_comments failed: %s", e)
            comments = []

        for c in comments:
            cid = int(c["id"])
            if cid in log_done:
                continue
            if "/trace" not in c.get("body", "").lower():
                continue
            try:
                reply_url = answer_one(client, gh, pr_url, session_id, cid, c["body"])
                if reply_url:
                    log.info("answered comment %d -> %s", cid, reply_url)
            except Exception as e:  # noqa: BLE001
                log.warning("answer failed for comment %d: %s", cid, e)
            finally:
                log_done.add(cid)

        if comments:
            last_since = comments[-1].get("created_at") or last_since

        if stop_after is not None and (time.time() - started) >= stop_after:
            return
        time.sleep(interval)
