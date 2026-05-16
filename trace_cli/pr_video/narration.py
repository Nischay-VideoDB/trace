"""Narration script generation via VideoDB-hosted LLM."""
from __future__ import annotations

import logging

from trace_cli.pr_video.selector import Clip
from trace_cli.session.models import Transcript, TranscriptSegment
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_video.narration")

MAX_CHARS = 1500


def _transcript_for_clip(transcript: Transcript, clip: Clip) -> str:
    parts: list[str] = []
    for seg in transcript.segments:
        if seg.end_seconds <= clip.start or seg.start_seconds >= clip.end:
            continue
        parts.append(seg.text.strip())
    return " ".join(p for p in parts if p)


def build_script(
    client: VideoDBClient,
    clips: list[Clip],
    transcript: Transcript,
    *,
    pr_title: str = "this change",
    pr_summary: str = "",
    model: str = "pro",
) -> str:
    """Compose narration <= MAX_CHARS using `coll.generate_text`.

    Falls back to a deterministic stitched script if the LLM call fails.
    """
    clip_blobs: list[str] = []
    for i, c in enumerate(clips, 1):
        spoken = _transcript_for_clip(transcript, c)
        file_hint = f" (file {c.file_path})" if c.file_path else ""
        blob = f"Clip {i} [{c.start:.1f}-{c.end:.1f}s {c.category}{file_hint}]: {c.evidence[:120]}"
        if spoken:
            blob += f" | spoken: {spoken[:200]}"
        clip_blobs.append(blob)
    clip_text = "\n".join(clip_blobs)

    prompt = (
        "You are writing a 60 to 75 second narration script for a PR walkthrough video. "
        "Speak in first person as the developer (\"I\"). Cover the why behind the change, not the diff. "
        "Use the user's own spoken words from the clips where they fit naturally. "
        "Keep sentences short. Plain English, no markdown, no stage directions. "
        f"Limit output to {MAX_CHARS} characters total.\n\n"
        f"PR title: {pr_title}\n"
        f"PR summary: {pr_summary[:500]}\n\n"
        f"Clips:\n{clip_text}\n\n"
        "Output only the narration text."
    )

    try:
        text = client.generate_text(prompt=prompt, model=model)
    except Exception as e:  # noqa: BLE001
        log.warning("generate_text failed (%s); using stitched fallback", e)
        spoken_bits = []
        for c in clips:
            s = _transcript_for_clip(transcript, c)
            if s:
                spoken_bits.append(s)
        fallback = (
            f"Here is what changed in {pr_title}. " + " ".join(spoken_bits)[:MAX_CHARS - 100]
        )
        return fallback[:MAX_CHARS]

    text = (text or "").strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(".", 1)[0] + "."
    return text or f"Walkthrough of {pr_title}."
