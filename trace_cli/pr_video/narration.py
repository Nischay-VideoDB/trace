"""Per-clip narration scripts via VideoDB-hosted LLM.

We generate one short script per clip so each chunk lines up with what is on
screen during that clip. Each chunk targets ~ duration*15 chars of speech.

Two passes:
  1. Anchor: one short overview line for the whole PR (~8s of TTS).
  2. Per-clip: a 4-12s script using the clip's spoken transcript + evidence.
"""
from __future__ import annotations

import logging

from trace_cli.pr_video.selector import Clip
from trace_cli.session.models import Transcript
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_video.narration")

CHARS_PER_SEC = 15
HARD_MAX = 2000


def _transcript_for_clip(transcript: Transcript, clip: Clip) -> str:
    parts: list[str] = []
    for seg in transcript.segments:
        if seg.end_seconds <= clip.start or seg.start_seconds >= clip.end:
            continue
        parts.append(seg.text.strip())
    return " ".join(p for p in parts if p)


def _trim_at_sentence(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    if last_period > max_chars * 0.4:
        return truncated[:last_period + 1]
    last_space = truncated.rfind(" ")
    return (truncated[:last_space] if last_space > 0 else truncated) + "."


def build_per_clip_scripts(
    client: VideoDBClient,
    clips: list[Clip],
    transcript: Transcript,
    *,
    pr_title: str = "this change",
    pr_summary: str = "",
    model: str = "pro",
) -> list[str]:
    """Generate a single PR-wide script then split into per-clip chunks.

    Single-pass approach so the LLM knows the full arc and avoids repeating
    itself across overlapping moments. We ask for delimited chunks (one per
    clip) and parse them out. Each chunk targets ~ duration*15 chars.
    """
    if not clips:
        return []

    # Attach spoken transcript to each clip.
    for c in clips:
        c.spoken = _transcript_for_clip(transcript, c)

    # Build a single prompt describing all clips as numbered chunks.
    chunk_specs = []
    for i, c in enumerate(clips):
        target_s = max(3, int(c.duration * 0.8))  # leave breathing room
        target_chars = max(60, int(target_s * CHARS_PER_SEC))
        kind = {
            "progress": "edit-and-save",
            "speech":   "thinking-out-loud",
            "research": "looking-things-up",
            "stuck":    "stuck",
        }.get(c.category, "general")
        file_hint = f" in {c.file_path}" if c.file_path else ""
        spoken = f' (I said: "{c.spoken[:200]}")' if c.spoken else ""
        chunk_specs.append(
            f"<chunk index={i} max_chars={target_chars} kind={kind}{file_hint}>{spoken}</chunk>"
        )

    total_target_chars = sum(max(60, int(c.duration * 0.8 * CHARS_PER_SEC)) for c in clips)
    prompt = (
        f"Write a PR walkthrough narration split across {len(clips)} sequential chunks. "
        "Each chunk plays over a different clip of the recording, so DO NOT repeat content "
        "from earlier chunks. Each chunk continues the story from the last. "
        "Speak in first person (I/me). Sound like the developer thinking out loud. "
        "Short sentences. Plain English. No markdown, no labels, no phrases like "
        "'in this clip' or 'now I will'.\n\n"
        f"PR: {pr_title}. {pr_summary[:200]}\n\n"
        "Chunks (preserve order, do not exceed each max_chars):\n"
        + "\n".join(chunk_specs)
        + "\n\nFormat your output EXACTLY like this, one chunk per line, no extra text:\n"
        "[0] <narration for chunk 0>\n"
        "[1] <narration for chunk 1>\n"
        f"... up to [{len(clips) - 1}]\n\n"
        f"Total budget is about {total_target_chars} characters across all chunks. "
        "The whole script should tell ONE coherent story arc with no repetition."
    )

    try:
        raw = client.generate_text(prompt=prompt, model=model)
    except Exception as e:  # noqa: BLE001
        log.warning("generate_text failed (%s); falling back to per-clip", e)
        raw = ""

    parsed = _parse_chunked_script(raw, len(clips)) if raw else [""] * len(clips)

    # Per-clip fallback for any missing/empty chunks.
    scripts: list[str] = []
    for i, c in enumerate(clips):
        text = parsed[i].strip() if i < len(parsed) else ""
        target_chars = max(60, int(c.duration * 0.8 * CHARS_PER_SEC))
        if not text:
            text = c.spoken or c.evidence or "Continuing the change."
        text = _trim_at_sentence(text, target_chars)
        scripts.append(text)
        log.info("clip %d narration: %d chars (target %d)", i, len(text), target_chars)
    return scripts


def _parse_chunked_script(raw: str, n: int) -> list[str]:
    """Parse '[0] ... [1] ...' format into list of length n."""
    import re
    pattern = re.compile(r"\[(\d+)\]\s*", re.MULTILINE)
    parts = pattern.split(raw)
    # parts: ['preface', '0', 'text0', '1', 'text1', ...]
    out: dict[int, str] = {}
    for j in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[j])
        except (ValueError, IndexError):
            continue
        out[idx] = parts[j + 1].strip()
    return [out.get(i, "") for i in range(n)]
