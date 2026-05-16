"""Narration script generation via VideoDB-hosted LLM."""
from __future__ import annotations

import logging

from trace_cli.pr_video.selector import Clip
from trace_cli.session.models import Transcript, TranscriptSegment
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_video.narration")

MAX_CHARS_HARD = 1500
# Empirical TTS pacing: ~15 chars per second of speech for openai/playai voices.
CHARS_PER_SEC = 15


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
    """Compose narration sized to the total clip duration.

    The narration must roughly fit the video runtime, otherwise TTS plays past
    the last frame and the overlay sounds disconnected. Target length is
    derived from clip total seconds at ~15 chars/sec, clamped to [200, 1500].
    """
    total_seconds = sum(c.duration for c in clips)
    target_chars = max(200, min(MAX_CHARS_HARD, int(total_seconds * CHARS_PER_SEC)))
    target_seconds = int(total_seconds)
    log.info(
        "narration budget: clips=%d total=%.1fs target_chars=%d",
        len(clips), total_seconds, target_chars,
    )

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
        f"Write a narration script of approximately {target_seconds} seconds, "
        f"strictly under {target_chars} characters. "
        "Speak in first person as the developer (use \"I\"). "
        "Cover the reasoning behind the change, not a line-by-line diff walkthrough. "
        "Lean on the user's own spoken words from the clips where they fit naturally. "
        "Short sentences. Plain English. No markdown, no stage directions, no headings. "
        f"If you can not fit everything in {target_chars} characters, cut detail rather than going over.\n\n"
        f"PR title: {pr_title}\n"
        f"PR summary: {pr_summary[:500]}\n\n"
        f"Clips:\n{clip_text}\n\n"
        "Output only the narration text. No preface, no closing remarks."
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
            f"Here is what changed in {pr_title}. " + " ".join(spoken_bits)[: target_chars - 100]
        )
        return fallback[:target_chars]

    text = (text or "").strip()
    if len(text) > target_chars:
        # Cut at last sentence boundary before the limit.
        truncated = text[:target_chars]
        last_period = truncated.rfind(".")
        if last_period > target_chars * 0.5:
            text = truncated[:last_period + 1]
        else:
            text = truncated.rsplit(" ", 1)[0] + "."
        log.info("trimmed script from %d -> %d chars", len(text), target_chars)
    return text or f"Walkthrough of {pr_title}."
