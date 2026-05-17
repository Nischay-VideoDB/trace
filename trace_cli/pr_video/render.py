"""PR video render via videodb.editor.Timeline.

Strategy:
  - Generate a reference voice clip first, then use OmniVoice voice-clone
    (ref_audio + ref_text) for every per-clip TTS call. Same voice guaranteed.
  - Per-clip TTS run in parallel (4 workers, same sandbox) so each audio
    asset has a measured .length — video clip trimmed to exactly that duration.
    Perfect sync, no char-count estimation.
  - Source video audio muted (volume=0) so narration is the only audio.
  - FLUX-generated intro title card (16:9, medium sandbox).
  - Background ambient music at low volume, starting after intro.
  - Fade transitions between clips.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass

from videodb import SandboxModel
from videodb.editor import (
    AudioAsset,
    Background,
    Clip,
    Fit,
    Font,
    ImageAsset,
    Position,
    TextAsset,
    Timeline,
    Track,
    Transition,
    VideoAsset,
)

from trace_cli.pr_video.selector import Clip as SelectedClip
from trace_cli.videodb.client import VideoDBClient

_CATEGORY_BADGE = {
    "progress": "EDIT",
    "speech":   "EXPLAIN",
    "research": "RESEARCH",
    "stuck":    "STUCK",
}

log = logging.getLogger("trace.pr_video.render")

_REF_TEXT = (
    "This is the reference voice for the trace session summary. "
    "I will narrate the key changes made during this coding session in a clear, confident tone."
)
_VOICE_INSTRUCTIONS = "clear, professional male tech narrator, measured pace, confident"
_MUSIC_PROMPT = "subtle ambient electronic background music for a software demo, very low energy, minimal"


def _badge_text(sc: SelectedClip) -> str:
    label = _CATEGORY_BADGE.get(sc.category, sc.category.upper())
    if sc.file_path:
        return f"trace  {label}  {os.path.basename(sc.file_path)}"
    return f"trace  {label}"


@dataclass
class RenderResult:
    hls_url: str
    narration_text: str
    narration_asset_ids: list[str]
    clip_count: int
    total_seconds: float


def _generate_clip_audio_cloned(args: tuple) -> tuple[int, object | None]:
    """Worker: generate TTS for one clip using voice clone. Returns (index, Audio|None)."""
    idx, text, collection, sandbox_id, ref_url, ref_text = args
    try:
        audio = collection.generate_voice(
            text=text,
            model_name=SandboxModel.OMNIVOICE,
            sandbox_id=sandbox_id,
            wait=True,
            timeout=600,
            poll_interval=5,
            config={
                "ref_audio": ref_url,
                "ref_text": ref_text,
                "response_format": "wav",
            },
        )
        log.info("clip %d audio: id=%s len=%.2fs", idx, getattr(audio, "id", "?"), getattr(audio, "length", 0))
        return idx, audio
    except Exception as e:  # noqa: BLE001
        log.warning("clip %d TTS failed: %s", idx, e)
        return idx, None


def render(
    client: VideoDBClient,
    video_id: str,
    clips: list[SelectedClip],
    per_clip_scripts: list[str],
    *,
    voice: str = "Default",
    source_volume: float = 0.0,
    pr_title: str = "",
) -> RenderResult:
    if not clips or not per_clip_scripts:
        raise ValueError("clips and per_clip_scripts must be non-empty")
    if len(clips) != len(per_clip_scripts):
        raise ValueError(f"clip/script count mismatch: {len(clips)} vs {len(per_clip_scripts)}")

    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("source video length: %.3fs", video_length)

    # 1. Spin up sandboxes.
    sandbox = client.ensure_sandbox(tier="small")
    sandbox_id = sandbox.id
    medium_sandbox_id = ""
    try:
        med = client.ensure_sandbox(tier="medium")
        medium_sandbox_id = med.id
        log.info("medium sandbox for FLUX: %s", medium_sandbox_id)
    except Exception as e:  # noqa: BLE001
        log.warning("medium sandbox unavailable (%s); skipping FLUX intro", e)

    # 2. Generate reference voice clip — all subsequent calls clone this voice.
    ref_url = ""
    ref_audio_id = ""
    try:
        log.info("generating reference voice (pins voice identity for all clips)")
        ref_audio = client._collection.generate_voice(
            text=_REF_TEXT,
            voice_name=voice,
            model_name=SandboxModel.OMNIVOICE,
            sandbox_id=sandbox_id,
            wait=True,
            timeout=300,
            poll_interval=5,
            config={
                "instructions": _VOICE_INSTRUCTIONS,
                "response_format": "wav",
            },
        )
        ref_url = ref_audio.generate_url()
        ref_audio_id = getattr(ref_audio, "id", "")
        log.info("reference voice: id=%s len=%.2fs", ref_audio_id, getattr(ref_audio, "length", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("reference voice generation failed (%s); clips will use voice_name only", e)

    # 3. Generate per-clip TTS in parallel using voice clone.
    log.info("generating %d clip narrations in parallel (sandbox=%s)", len(per_clip_scripts), sandbox_id)
    clip_audios: list[object | None] = [None] * len(per_clip_scripts)

    if ref_url:
        args_list = [
            (i, script, client._collection, sandbox_id, ref_url, _REF_TEXT)
            for i, script in enumerate(per_clip_scripts)
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for idx, audio in pool.map(_generate_clip_audio_cloned, args_list):
                clip_audios[idx] = audio
    else:
        # Fallback: single combined TTS (one voice, no clone).
        log.info("fallback: single combined TTS for all clips")
        combined = " ... ".join(per_clip_scripts)
        try:
            combined_audio = client._collection.generate_voice(
                text=combined,
                voice_name=voice,
                model_name=SandboxModel.OMNIVOICE,
                sandbox_id=sandbox_id,
                wait=True,
                timeout=900,
                poll_interval=5,
            )
            # Distribute combined audio to all clips equally (approximate).
            n = len(per_clip_scripts)
            for i in range(n):
                clip_audios[i] = combined_audio  # will be placed sequentially
        except Exception as e:  # noqa: BLE001
            log.warning("fallback combined TTS failed: %s", e)

    # 4. Generate FLUX intro title card.
    intro_image_id = ""
    intro_audio_id = ""
    intro_dur = 0.0
    intro_script = f"trace session summary. {pr_title}." if pr_title else "trace — session summary."
    if medium_sandbox_id:
        try:
            log.info("generating FLUX intro title card")
            intro_image = client._collection.generate_image(
                prompt=(
                    "Dark minimal tech background. Large white sans-serif text 'trace' centered. "
                    "Small subtitle: 'session summary'. Clean developer aesthetic, no gradients, dark charcoal background."
                ),
                aspect_ratio="16:9",
                model_name=SandboxModel.FLUX,
                sandbox_id=medium_sandbox_id,
                config={"num_inference_steps": 28, "guidance_scale": 4.0},
                wait=True,
                timeout=600,
                poll_interval=5,
            )
            intro_image_id = getattr(intro_image, "id", "")
            log.info("FLUX intro image: id=%s", intro_image_id)

            # Intro narration — cloned voice if available.
            intro_voice_cfg: dict = {"response_format": "wav"}
            if ref_url:
                intro_voice_cfg["ref_audio"] = ref_url
                intro_voice_cfg["ref_text"] = _REF_TEXT
            else:
                intro_voice_cfg["instructions"] = _VOICE_INSTRUCTIONS

            intro_voice = client._collection.generate_voice(
                text=intro_script,
                model_name=SandboxModel.OMNIVOICE,
                sandbox_id=sandbox_id,
                wait=True,
                timeout=300,
                poll_interval=5,
                config=intro_voice_cfg,
            )
            intro_audio_id = getattr(intro_voice, "id", "")
            intro_dur = float(getattr(intro_voice, "length", 0.0) or 0.0)
            log.info("intro audio: id=%s len=%.2fs", intro_audio_id, intro_dur)
        except Exception as e:  # noqa: BLE001
            log.warning("intro generation failed (%s); skipping intro", e)
            intro_image_id = ""

    # 5. Generate background ambient music (no sandbox needed).
    music_id = ""
    music_len = 0.0
    try:
        est_total = intro_dur + sum(
            float(getattr(a, "length", 8.0) or 8.0) for a in clip_audios if a is not None
        )
        music_dur = max(30, int(est_total) + 10)
        log.info("generating ambient music: %ds", music_dur)
        music = client._collection.generate_music(
            prompt=_MUSIC_PROMPT,
            duration=music_dur,
        )
        music_id = getattr(music, "id", "")
        music_len = float(getattr(music, "length", 0.0) or 0.0)
        log.info("music: id=%s len=%.2fs", music_id, music_len)
    except Exception as e:  # noqa: BLE001
        log.warning("music generation failed (%s); skipping music", e)

    # 6. Build timeline.
    tl = Timeline(client._conn)
    tl.resolution = "1280x720"
    tl.background = "#000000"

    video_track = Track()
    narration_track = Track()
    badge_track = Track()
    music_track = Track()

    cursor = 0  # integer seconds
    placed = 0
    all_audio_ids: list[str] = []
    combined_script_parts: list[str] = []

    # 6a. Intro segment (FLUX image + narration).
    content_start = 0
    if intro_image_id and intro_dur > 0:
        intro_clip_dur = max(3.0, intro_dur + 1.0)
        video_track.add_clip(cursor, Clip(
            asset=ImageAsset(id=intro_image_id),
            duration=intro_clip_dur,
            fit=Fit.crop,
            transition=Transition(in_="fade", out="fade", duration=0.5),
        ))
        if intro_audio_id:
            narration_track.add_clip(cursor, Clip(
                asset=AudioAsset(id=intro_audio_id, volume=1.0),
                duration=intro_dur,
            ))
            all_audio_ids.append(intro_audio_id)
            combined_script_parts.append(intro_script)
        cursor += int(round(intro_clip_dur))
        content_start = cursor

    # 6b. Content clips — video trimmed to exact audio duration.
    for i, (sc, audio) in enumerate(zip(clips, clip_audios)):
        if audio is None:
            log.warning("clip %d: no audio, skipping", i)
            continue

        aud_dur = float(getattr(audio, "length", 0.0) or 0.0)
        if aud_dur < 0.5:
            log.warning("clip %d: audio too short (%.2fs), skipping", i, aud_dur)
            continue

        src_start = int(max(0, sc.start))
        src_dur = max(0.5, sc.end - sc.start)
        # Video shows for max(narration_length, source_clip_duration) so the
        # screen stays on the relevant moment even if narration ends early.
        output_dur = max(aud_dur, src_dur)
        if video_length > 0:
            max_src_end = video_length - 0.1
            output_dur = min(output_dur, max_src_end - src_start)
        output_dur = max(aud_dur, 2.0)  # always at least as long as audio

        video_track.add_clip(cursor, Clip(
            asset=VideoAsset(id=video_id, start=src_start, volume=0),
            duration=output_dur,
            transition=Transition(in_="fade", out="fade", duration=0.5),
        ))

        audio_id = getattr(audio, "id", "")
        narration_track.add_clip(cursor, Clip(
            asset=AudioAsset(id=audio_id, volume=1.0),
            duration=aud_dur,
        ))
        all_audio_ids.append(audio_id)
        combined_script_parts.append(per_clip_scripts[i])

        try:
            badge = TextAsset(
                text=_badge_text(sc),
                font=Font(family="Clear Sans", size=28, color="#FFFFFF", opacity=1.0),
                background=Background(width=0.0, height=0.0, color="#000000", opacity=0.75),
            )
            badge_track.add_clip(cursor, Clip(
                asset=badge,
                duration=output_dur,
                position=Position.top_left,
                opacity=0.9,
            ))
        except Exception as e:  # noqa: BLE001
            log.debug("badge skipped for clip %d: %s", i, e)

        cursor += int(round(output_dur))
        placed += 1

    total_seconds = float(cursor)

    # 6c. Music starts after intro (so narration isn't drowned in intro).
    if music_id and music_len > 0:
        music_content_dur = min(music_len, total_seconds - content_start)
        if music_content_dur > 0:
            music_track.add_clip(content_start, Clip(
                asset=AudioAsset(id=music_id, volume=0.08),
                duration=music_content_dur,
            ))

    tl.add_track(music_track)
    tl.add_track(video_track)
    tl.add_track(narration_track)
    tl.add_track(badge_track)

    log.info(
        "timeline: intro=%s %d clips placed total=%.1fs",
        "yes" if intro_image_id else "no",
        placed,
        total_seconds,
    )

    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"timeline.generate_stream failed: {e}") from e

    return RenderResult(
        hls_url=url,
        narration_text=" | ".join(combined_script_parts),
        narration_asset_ids=all_audio_ids,
        clip_count=placed,
        total_seconds=total_seconds,
    )
