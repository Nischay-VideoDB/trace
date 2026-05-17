"""PR description: What changed (diff) + Why (voice + intent) + Struggles + Follow-ups.

Composed by VideoDB.generate_text with grounding from:
  - file diff (what changed)
  - session transcript (why, from developer's own words)
  - timeline 'stuck' moments (what you struggled with)
  - any followup phrases in transcript ("come back", "todo", "later")
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


@dataclass
class PRDescription:
    body: str
    video_url: str | None
    contribution_url: str | None


def _file_bullets(files: list[dict], max_files: int = 50) -> list[str]:
    bullets = []
    for f in files[:max_files]:
        path = f.get("path", "")
        adds = int(f.get("additions", 0) or 0)
        dels = int(f.get("deletions", 0) or 0)
        bullets.append(f"- `{path}` (+{adds} -{dels})")
    if len(files) > max_files:
        extra = len(files) - max_files
        bullets.append(f"- _+ {extra} more files_")
    return bullets


def _all_transcript_text(transcript: Transcript) -> str:
    return " ".join(seg.text.strip() for seg in transcript.segments if seg.text.strip())


def _summarize_long_transcript(
    client: VideoDBClient,
    transcript: Transcript,
    *,
    model: str = "pro",
    chunk_chars: int = 3500,
) -> str:
    """For long sessions, page through transcript in chunks of ~3500 chars,
    summarize each chunk, then summarize the summaries. Avoids LLM context
    truncation that would silently drop 90% of a 2-hour session.
    """
    full = _all_transcript_text(transcript)
    if len(full) <= chunk_chars:
        return full

    log.info("long transcript (%d chars): paging summary in chunks of %d", len(full), chunk_chars)
    chunks: list[str] = []
    for i in range(0, len(full), chunk_chars):
        chunk = full[i:i + chunk_chars]
        try:
            summary = client.generate_text(
                prompt=(
                    "Summarize this slice of a developer's spoken transcript in 2-3 sentences. "
                    "First person. Faithful only. Do not invent.\n\n"
                    f"Transcript slice:\n{chunk}\n\nOutput only the summary."
                ),
                model=model,
            ).strip()
            if summary:
                chunks.append(summary)
        except Exception as e:  # noqa: BLE001
            log.warning("transcript chunk summary failed (%s); using verbatim", e)
            chunks.append(chunk[:500])
    return " ".join(chunks)[:6000]


def _stuck_moments_text(timeline: Timeline) -> list[str]:
    return [m.evidence[:160] for m in timeline.moments if m.category == "stuck" and m.evidence]


def _followup_quotes(transcript: Transcript) -> list[str]:
    return [
        seg.text.strip()
        for seg in transcript.segments
        if FOLLOWUP_RE.search(seg.text or "")
    ][:5]


def build(
    client: VideoDBClient,
    files: list[dict],
    transcript: Transcript,
    timeline: Timeline,
    *,
    pr_title: str = "",
    video_url: str | None = None,
    contribution_url: str | None = None,
    preview_gif_url: str | None = None,
    model: str = "pro",
) -> PRDescription:
    bullets = _file_bullets(files)
    spoken = _summarize_long_transcript(client, transcript, model=model)
    stuck_bits = _stuck_moments_text(timeline)
    followups = _followup_quotes(transcript)

    why_prompt = (
        "Write the 'Why' section of a PR description, max 5 sentences. Speak in first "
        "person as the developer. Stay strictly faithful to what the developer actually "
        "said in the transcript below. Do not invent technical claims. Focus on the "
        "motivation and the decisions, not a line-by-line summary of the diff.\n\n"
        f"PR title: {pr_title}\n\n"
        f"Transcript from the coding session:\n{spoken}\n\n"
        "Output the Why text only, no headings."
    )
    try:
        why = client.generate_text(prompt=why_prompt, model=model).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("generate_text(why) failed (%s); using transcript verbatim", e)
        why = spoken[:600] or "_no spoken explanation captured during the session._"
    if len(why) > 1500:
        why = why[:1500].rsplit(".", 1)[0] + "."

    sections: list[str] = []
    if preview_gif_url:
        sections.append(
            f"## trace walkthrough\n\n"
            f"![preview]({preview_gif_url})\n\n"
            f"_Silent 10s preview. Full narrated video: {video_url}_\n"
        )
    sections.append("\n## What changed\n\n" + "\n".join(bullets) if bullets else "\n## What changed\n\n_no files in diff._")
    sections.append("\n## Why\n\n" + why)

    if stuck_bits:
        sections.append(
            "\n## Struggles\n\n"
            + "\n".join(f"- {s}" for s in stuck_bits[:5])
        )

    if followups:
        sections.append(
            "\n## Follow-ups\n\n"
            + "\n".join(f"- _{q}_" for q in followups)
        )

    if video_url:
        sections.append(f"\n## Walkthrough video\n\n{video_url}")
    if contribution_url:
        sections.append(f"\n## Contribution map\n\nSee posted comment: {contribution_url}")

    sections.append(
        "\n---\n_Generated by [trace](https://github.com/) from your recorded session. "
        "Built on VideoDB._"
    )
    return PRDescription(
        body="\n".join(sections),
        video_url=video_url,
        contribution_url=contribution_url,
    )
