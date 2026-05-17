"""Per-clip narration scripts via VideoDB-hosted LLM.

For each clip we pass two ground-truth inputs to the LLM so it does not
hallucinate:
  spoken: the user's transcript words during that clip window.
  scene:  the VideoDB scene-index summary of what is visible on screen
          during that clip window (label, files, errors, summary).

A single LLM call returns delimited per-clip chunks so the model has full
context and never repeats itself across overlapping clips.
"""
from __future__ import annotations

import json
import logging
import re

from trace_cli.pr_video.selector import Clip
from trace_cli.session.models import Transcript
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_video.narration")

CHARS_PER_SEC = 13  # OmniVoice measured ~12-14 cps at normal pace
HARD_MAX = 2000


def _transcript_for_clip(transcript: Transcript, clip: Clip) -> str:
    parts: list[str] = []
    for seg in transcript.segments:
        if seg.end_seconds <= clip.start or seg.start_seconds >= clip.end:
            continue
        parts.append(seg.text.strip())
    return " ".join(p for p in parts if p)


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_scene_desc(desc: str) -> dict:
    """Scene `description` is often a fenced JSON block; extract the dict."""
    if not desc:
        return {}
    m = _FENCED_JSON_RE.search(desc)
    raw = m.group(1) if m else desc.strip()
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        # Fall back: treat the whole description as summary text.
        return {"summary": desc[:200]}


def _scenes_for_clip(scenes: list[dict], clip: Clip) -> list[dict]:
    """Return scene-index entries that overlap this clip."""
    out: list[dict] = []
    for s in scenes:
        s_start = float(s.get("start", 0.0) or 0.0)
        s_end = float(s.get("end", 0.0) or 0.0)
        if s_end <= clip.start or s_start >= clip.end:
            continue
        parsed = _parse_scene_desc(s.get("description", ""))
        parsed["_start"] = s_start
        parsed["_end"] = s_end
        out.append(parsed)
    return out


def _format_scene_for_prompt(scenes: list[dict]) -> str:
    """Compress a list of scene dicts into a short human readable summary."""
    if not scenes:
        return ""
    bits: list[str] = []
    for sc in scenes:
        label = sc.get("label", "")
        summary = sc.get("summary", "")
        files = sc.get("files") or []
        errors = sc.get("errors") or []
        chunk = f"[{sc.get('_start',0):.0f}-{sc.get('_end',0):.0f}s {label}]"
        if files:
            chunk += f" files={','.join(files[:3])}"
        if errors:
            chunk += f" errors={errors[0][:80]!r}"
        if summary:
            chunk += f" {summary[:140]}"
        bits.append(chunk)
    return " | ".join(bits)


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
    scenes: list[dict] | None = None,
) -> list[str]:
    """Generate per-clip narration grounded in scene + transcript.

    Pass `scenes` from `VideoDBClient.get_scenes(video, scene_index_id)` to
    give the LLM ground truth about what is visually on screen for each clip.
    Without scenes the model can hallucinate technical detail.
    """
    if not clips:
        return []
    scenes = scenes or []

    for c in clips:
        c.spoken = _transcript_for_clip(transcript, c)

    chunk_specs = []
    for i, c in enumerate(clips):
        target_s = max(3, int(c.duration))
        target_chars = max(80, int(target_s * CHARS_PER_SEC))
        kind = {
            "progress": "edit-and-save",
            "speech":   "thinking-out-loud",
            "research": "looking-things-up",
            "stuck":    "stuck",
        }.get(c.category, "general")
        file_hint = f" in {c.file_path}" if c.file_path else ""
        spoken = f' I said: "{c.spoken[:200]}"' if c.spoken else " I said nothing."
        scene_text = _format_scene_for_prompt(_scenes_for_clip(scenes, c))
        scene_hint = f" On screen: {scene_text[:400]}" if scene_text else ""
        chunk_specs.append(
            f"<chunk index={i} target_chars={target_chars} kind={kind}{file_hint}>"
            f"{spoken}{scene_hint}</chunk>"
        )

    total_target_chars = sum(max(80, int(c.duration * CHARS_PER_SEC)) for c in clips)
    prompt = (
        f"Write a PR walkthrough narration split across {len(clips)} sequential chunks. "
        "Each chunk plays over a different clip of the recording, so DO NOT repeat content "
        "from earlier chunks. Each chunk continues the story from the last.\n\n"
        "GROUND TRUTH RULES:\n"
        "- The 'I said' field is the developer's actual transcribed words. Stay faithful "
        "to that intent. Paraphrase for clarity but do not invent specific technical claims "
        "the developer did not make.\n"
        "- The 'On screen' field tells you what is visually present (terminal, browser, "
        "code editor, files, errors). Describe what is shown, not what you imagine.\n"
        "- If both fields are sparse, keep the chunk short and generic. Do NOT invent "
        "function names, error messages, decisions, or technical reasoning that has no "
        "support in the provided context.\n\n"
        "STYLE:\n"
        "- Speak in first person (I/me). Sound like the developer narrating their own "
        "session in a calm, factual voice. Short sentences. Plain English. "
        "No markdown, no labels, no phrases like 'in this clip' or 'now I will'.\n\n"
        f"PR: {pr_title}. {pr_summary[:200]}\n\n"
        "Chunks (each chunk MUST reach its target_chars — fill the time, don't cut short):\n"
        + "\n".join(chunk_specs)
        + "\n\nFormat output EXACTLY like this, one chunk per line, no extra text:\n"
        "[0] <narration for chunk 0>\n"
        "[1] <narration for chunk 1>\n"
        f"... up to [{len(clips) - 1}]\n\n"
        f"Total target: {total_target_chars} characters across all chunks. "
        "Each chunk must be close to its target_chars. Expand with relevant detail from context. "
        "One coherent story arc, no repetition, no hallucination."
    )

    # For long sessions (many clips), batch into groups of 6 per LLM call to
    # stay under context limits and keep narration coherent within each batch.
    BATCH = 6
    if len(clips) > BATCH:
        log.info("long session: batching %d clips into groups of %d", len(clips), BATCH)
        parsed: list[str] = []
        # Re-build prompts per batch using the same chunk_specs slices.
        for offset in range(0, len(clips), BATCH):
            batch_specs = chunk_specs[offset:offset + BATCH]
            batch_size = len(batch_specs)
            batch_prompt = prompt.replace(
                f"split across {len(clips)} sequential chunks",
                f"split across {batch_size} sequential chunks (this is batch starting at clip {offset + 1})"
            )
            batch_prompt = batch_prompt.replace(
                "\n".join(chunk_specs),
                "\n".join(batch_specs),
            )
            batch_prompt = batch_prompt.replace(
                f"... up to [{len(clips) - 1}]",
                f"... up to [{batch_size - 1}]",
            )
            try:
                raw_batch = client.generate_text(prompt=batch_prompt, model=model)
            except Exception as e:  # noqa: BLE001
                log.warning("batch %d generate_text failed (%s)", offset // BATCH, e)
                raw_batch = ""
            parsed.extend(_parse_chunked_script(raw_batch, batch_size) if raw_batch else [""] * batch_size)
    else:
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
        target_chars = max(80, int(c.duration * CHARS_PER_SEC))
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
