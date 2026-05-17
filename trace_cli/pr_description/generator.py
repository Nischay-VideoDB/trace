"""PR description: structured, clean, grounded in session data.

Sections:
  - Walkthrough (thumbnail + HLS link)
  - Summary (1-2 sentence LLM)
  - What changed (diff files, junk filtered)
  - Why (from spoken transcript)
  - Struggles (stuck moments)
  - Follow-ups (todo/fixme quotes)
  - Test plan (from timeline + transcript)
  - Contribution map link

If the repo has a CONTRIBUTING.md or .github/pull_request_template.md,
fetch it and ask the LLM to match that format instead of the default.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from trace_cli.session.models import Timeline, Transcript
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_description")

FOLLOWUP_RE = re.compile(
    r"\b(todo|fixme|come back|later|follow.?up|next time|next step|need to also)\b",
    re.IGNORECASE,
)

_JUNK_PATH_RE = re.compile(
    r"(__pycache__|\.pyc$|\.pytest_cache|\.egg-info|node_modules|dist-info|\.DS_Store)"
)


@dataclass
class PRDescription:
    body: str
    video_url: str | None
    contribution_url: str | None


def _file_bullets(files: list[dict], max_files: int = 20) -> list[str]:
    bullets = []
    skipped = 0
    for f in files:
        path = f.get("path", "")
        if _JUNK_PATH_RE.search(path):
            skipped += 1
            continue
        adds = int(f.get("additions", 0) or 0)
        dels = int(f.get("deletions", 0) or 0)
        if adds == 0 and dels == 0:
            skipped += 1
            continue
        bullets.append(f"- `{path}` (+{adds} -{dels})")
        if len(bullets) >= max_files:
            break
    remaining = len(files) - len(bullets) - skipped
    if remaining > 0:
        bullets.append(f"- _...and {remaining} more_")
    return bullets


def _all_transcript_text(transcript: Transcript) -> str:
    return " ".join(seg.text.strip() for seg in transcript.segments if seg.text.strip())


def _summarize_transcript(client: VideoDBClient, transcript: Transcript, model: str) -> str:
    full = _all_transcript_text(transcript)
    if not full:
        return ""
    chunk_chars = 3500
    if len(full) <= chunk_chars:
        return full
    chunks: list[str] = []
    for i in range(0, len(full), chunk_chars):
        chunk = full[i:i + chunk_chars]
        try:
            s = client.generate_text(
                prompt=(
                    "Summarize this slice of a developer's spoken transcript in 2-3 sentences. "
                    "First person. Faithful only. Do not invent.\n\n"
                    f"Transcript:\n{chunk}\n\nOutput only the summary."
                ),
                model=model,
            ).strip()
            if s:
                chunks.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("transcript chunk summary failed: %s", e)
            chunks.append(chunk[:400])
    return " ".join(chunks)[:6000]


def _fetch_pr_template(owner: str, repo: str, token: str) -> str | None:
    """Try to fetch CONTRIBUTING.md or PR template from the repo."""
    import urllib.request
    candidates = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/.github/pull_request_template.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/CONTRIBUTING.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/.github/CONTRIBUTING.md",
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 200:
                    content = r.read().decode("utf-8", errors="replace")
                    if len(content) > 50:
                        log.info("found PR template at %s (%d chars)", url, len(content))
                        return content[:3000]
        except Exception:  # noqa: BLE001
            continue
    return None


def build(
    client: VideoDBClient,
    files: list[dict],
    transcript: Transcript,
    timeline: Timeline,
    *,
    pr_title: str = "",
    video_url: str | None = None,
    contribution_url: str | None = None,
    preview_thumb_url: str | None = None,
    pr_ref=None,
    model: str = "pro",
) -> PRDescription:
    import os
    token = os.environ.get("GITHUB_TOKEN", "")

    # Fetch repo PR template if available.
    pr_template: str | None = None
    if pr_ref and token:
        try:
            pr_template = _fetch_pr_template(pr_ref.owner, pr_ref.repo, token)
        except Exception as e:  # noqa: BLE001
            log.debug("template fetch failed: %s", e)

    bullets = _file_bullets(files)
    spoken = _summarize_transcript(client, transcript, model=model)
    stuck_bits = [m.evidence[:200] for m in timeline.moments if m.category == "stuck" and m.evidence]
    followups = [
        seg.text.strip()
        for seg in transcript.segments
        if FOLLOWUP_RE.search(seg.text or "")
    ][:4]

    # LLM-generated sections.
    if pr_template:
        # Ask LLM to fill in the repo's own template.
        fill_prompt = (
            f"Fill in this PR description template using ONLY information from the session data below. "
            f"Do not invent technical claims. Keep each section concise.\n\n"
            f"Template:\n{pr_template}\n\n"
            f"PR title: {pr_title}\n"
            f"Files changed:\n" + "\n".join(bullets) + "\n\n"
            f"Developer transcript:\n{spoken[:3000]}\n\n"
            f"Output only the filled template, no extra commentary."
        )
        try:
            filled = client.generate_text(prompt=fill_prompt, model=model).strip()
        except Exception as e:  # noqa: BLE001
            log.warning("template fill failed: %s", e)
            filled = ""
        if filled and len(filled) > 100:
            # Prepend trace video block then the filled template.
            sections: list[str] = []
            _append_video_block(sections, video_url, preview_thumb_url)
            sections.append(filled)
            _append_footer(sections, contribution_url)
            return PRDescription(
                body="\n\n".join(s.strip() for s in sections if s.strip()),
                video_url=video_url,
                contribution_url=contribution_url,
            )

    # Default structured format.
    why_prompt = (
        "Write the 'Why' section of a PR description in 3-5 sentences. "
        "Speak in first person as the developer. "
        "Stay strictly faithful to the transcript — no invented claims. "
        "Focus on motivation and decisions, not a diff summary.\n\n"
        f"PR title: {pr_title}\n"
        f"Transcript:\n{spoken[:3000]}\n\n"
        "Output the Why text only, no heading."
    )
    try:
        why = client.generate_text(prompt=why_prompt, model=model).strip()
        if len(why) > 1200:
            why = why[:1200].rsplit(".", 1)[0] + "."
    except Exception as e:  # noqa: BLE001
        log.warning("generate_text(why) failed: %s", e)
        why = spoken[:600] or "_no spoken explanation captured._"

    summary_prompt = (
        "Write a single sentence (max 25 words) summarizing what changed in this PR.\n\n"
        f"PR title: {pr_title}\n"
        f"Files: {', '.join(b.strip('- ').split(' ')[0] for b in bullets[:6])}\n"
        f"Transcript excerpt: {spoken[:800]}\n\n"
        "Output only the sentence."
    )
    try:
        summary = client.generate_text(prompt=summary_prompt, model="basic").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("generate_text(summary) failed: %s", e)
        summary = ""

    sections = []
    _append_video_block(sections, video_url, preview_thumb_url)

    if summary:
        sections.append(f"> {summary}")

    sections.append("## What changed\n\n" + ("\n".join(bullets) if bullets else "_no diff_"))
    sections.append("## Why\n\n" + why)

    if stuck_bits:
        sections.append("## Struggles\n\n" + "\n".join(f"- {s}" for s in stuck_bits[:4]))

    if followups:
        sections.append("## Follow-ups\n\n" + "\n".join(f"- {q}" for q in followups))

    # Test plan: infer from transcript + timeline.
    test_mentions = [
        seg.text.strip()
        for seg in transcript.segments
        if re.search(r"\b(test|pytest|assert|check|verify|pass|fail)\b", seg.text or "", re.IGNORECASE)
    ][:4]
    if test_mentions:
        sections.append(
            "## Test plan\n\n"
            + "\n".join(f"- {t[:120]}" for t in test_mentions)
        )

    _append_footer(sections, contribution_url)

    return PRDescription(
        body="\n\n".join(s.strip() for s in sections if s.strip()),
        video_url=video_url,
        contribution_url=contribution_url,
    )


def _append_video_block(sections: list[str], video_url: str | None, thumb_url: str | None) -> None:
    if not video_url:
        return
    if thumb_url:
        sections.append(
            f"## trace walkthrough\n\n"
            f"[![narrated session walkthrough]({thumb_url})]({video_url})\n\n"
            f"_Click to play the narrated walkthrough._"
        )
    else:
        sections.append(f"## trace walkthrough\n\n[Watch narrated walkthrough]({video_url})")


def _append_footer(sections: list[str], contribution_url: str | None) -> None:
    footer_parts = ["_Generated by [trace](https://github.com/crypticsaiyan/trace) from recorded session._"]
    if contribution_url:
        footer_parts.append(f"[Contribution map]({contribution_url})")
    sections.append("---\n" + " · ".join(footer_parts))
