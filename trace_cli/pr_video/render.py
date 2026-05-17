"""PR video render via videodb.editor.Timeline.

Strategy:
  - Generate TTS per clip in parallel (same sandbox) so each audio asset has
    a measured .length — video clip is trimmed to exactly that duration.
    This gives perfect sync without any char-count estimation.
  - Source video audio muted (volume=0) so narration is the only voice.
  - FLUX-generated intro title card (16:9, 1280x720).
  - Background ambient music at low volume underneath narration.
  - Fade transitions between clips.
  - OmniVoice with voice instructions for consistent professional quality.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass, field

from videodb import SandboxModel, SandboxTier
from videodb.editor import (
    AudioAsset,
    Background,
    Clip,
    Filter,
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

_VOICE_INSTRUCTIONS = "clear, professional male tech narrator, measured pace, confident"
_MUSIC_PROMPT = "subtle ambient background music for a software demo, low energy, not distracting"


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


def _generate_clip_audio(args: tuple) -> tuple[int, object | None]:
    """Worker: generate TTS for one clip. Returns (index, Audio|None)."""
    idx, text, client, voice, sandbox_id = args
    try:
        audio = client._collection.generate_voice(
            text=text,
            voice_name=voice,
            model_name=SandboxModel.OMNIVOICE,
            sandbox_id=sandbox_id,
            wait=True,
            timeout=600,
            poll_interval=5,
            config={
                "instructions": _VOICE_INSTRUCTIONS,
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

    # 1. Spin up sandboxes — small for OmniVoice TTS, medium for FLUX images.
    sandbox = client.ensure_sandbox(tier="small")
    sandbox_id = sandbox.id
    medium_sandbox_id = ""
    try:
        med = client.ensure_sandbox(tier="medium")
        medium_sandbox_id = med.id
        log.info("medium sandbox for FLUX: %s", medium_sandbox_id)
    except Exception as e:  # noqa: BLE001
        log.warning("medium sandbox unavailable (%s); skipping FLUX intro", e)

    # 2. Generate per-clip TTS in parallel (all on same sandbox — concurrent jobs fine).
    log.info("generating %d clip narrations in parallel (sandbox=%s)", len(per_clip_scripts), sandbox_id)
    clip_audios: list[object | None] = [None] * len(per_clip_scripts)
    args_list = [
        (i, script, client, voice, sandbox_id)
        for i, script in enumerate(per_clip_scripts)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for idx, audio in pool.map(_generate_clip_audio, args_list):
            clip_audios[idx] = audio

    # 3. Generate FLUX intro title card.
    intro_audio_id = ""
    intro_dur = 0.0
    intro_image_id = ""
    intro_script = f"trace — session summary. {pr_title}" if pr_title else "trace — session summary"
    try:
        if not medium_sandbox_id:
            raise RuntimeError("no medium sandbox for FLUX")
        log.info("generating FLUX intro title card (medium sandbox)")
        intro_image = client._collection.generate_image(
            prompt=(
                "Dark minimal tech background. Large white text 'trace' centered. "
                "Subtitle: 'session summary'. Clean developer aesthetic, no gradients."
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

        intro_voice_job = client._collection.generate_voice(
            text=intro_script,
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
        intro_audio_id = getattr(intro_voice_job, "id", "")
        intro_dur = float(getattr(intro_voice_job, "length", 0.0) or 0.0)
        log.info("intro audio: id=%s len=%.2fs", intro_audio_id, intro_dur)
    except Exception as e:  # noqa: BLE001
        log.warning("intro generation failed (%s); skipping intro", e)

    # 4. Generate background ambient music.
    total_estimated = intro_dur + sum(
        float(getattr(a, "length", 8.0) or 8.0) for a in clip_audios if a is not None
    )
    music_id = ""
    music_len = 0.0
    try:
        music_dur = max(30, int(total_estimated) + 5)
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

    # 5. Build timeline.
    tl = Timeline(client._conn)
    tl.resolution = "1280x720"
    tl.background = "#000000"

    video_track = Track()
    narration_track = Track()
    badge_track = Track()
    music_track = Track()

    cursor = 0  # integer seconds, accumulate
    placed = 0
    all_audio_ids: list[str] = []
    combined_script_parts: list[str] = []

    # 5a. Intro segment.
    if intro_image_id and intro_dur > 0:
        intro_clip_dur = max(3.0, intro_dur + 1.0)
        img_asset = ImageAsset(id=intro_image_id)
        img_clip = Clip(
            asset=img_asset,
            duration=intro_clip_dur,
            fit=Fit.crop,
            transition=Transition(in_="fade", out="fade", duration=0.5),
        )
        video_track.add_clip(cursor, img_clip)

        if intro_audio_id:
            a_clip = Clip(asset=AudioAsset(id=intro_audio_id, volume=1.0), duration=intro_dur)
            narration_track.add_clip(cursor, a_clip)
            all_audio_ids.append(intro_audio_id)
            combined_script_parts.append(intro_script)

        cursor += int(round(intro_clip_dur))

    # 5b. Content clips — video trimmed to exact audio duration.
    for i, (sc, audio) in enumerate(zip(clips, clip_audios)):
        if audio is None:
            log.warning("clip %d: no audio, skipping", i)
            continue

        aud_dur = float(getattr(audio, "length", 0.0) or 0.0)
        if aud_dur < 0.5:
            log.warning("clip %d: audio too short (%.2fs), skipping", i, aud_dur)
            continue

        # Video source window — trim to exact narration length.
        src_start = int(max(0, sc.start))
        src_end_target = sc.start + aud_dur
        if video_length > 0:
            src_end_target = min(video_length - 0.1, src_end_target)
        actual_src_dur = max(0.1, src_end_target - src_start)

        # If source segment shorter than narration, use what we have (audio continues over next clip).
        output_dur = aud_dur  # video clip = exact audio duration for this segment

        v_asset = VideoAsset(id=video_id, start=src_start, volume=0)  # muted — narration only
        v_clip = Clip(
            asset=v_asset,
            duration=output_dur,
            transition=Transition(in_="fade", out="fade", duration=0.5),
        )
        video_track.add_clip(cursor, v_clip)

        a_asset = AudioAsset(id=getattr(audio, "id", ""), volume=1.0)
        a_clip = Clip(asset=a_asset, duration=aud_dur)
        narration_track.add_clip(cursor, a_clip)
        all_audio_ids.append(getattr(audio, "id", ""))
        combined_script_parts.append(per_clip_scripts[i])

        # Badge overlay — category label + filename.
        try:
            badge = TextAsset(
                text=_badge_text(sc),
                font=Font(family="Clear Sans", size=28, color="#FFFFFF", opacity=1.0),
                background=Background(width=0.0, height=0.0, color="#000000", opacity=0.75),
            )
            badge_clip = Clip(
                asset=badge,
                duration=output_dur,
                position=Position.top_left,
                opacity=0.9,
            )
            badge_track.add_clip(cursor, badge_clip)
        except Exception as e:  # noqa: BLE001
            log.debug("badge skipped for clip %d: %s", i, e)

        cursor += int(round(output_dur))
        placed += 1

    total_seconds = float(cursor)

    # 5c. Background music track — full timeline length.
    if music_id and music_len > 0:
        effective_len = min(music_len, total_seconds)
        m_clip = Clip(asset=AudioAsset(id=music_id, volume=0.12), duration=effective_len)
        music_track.add_clip(0, m_clip)

    # Add tracks (order = z-order, later = on top for visual; audio mixes).
    tl.add_track(music_track)
    tl.add_track(video_track)
    tl.add_track(narration_track)
    tl.add_track(badge_track)

    log.info(
        "timeline: intro=%s %d clips placed, total=%.1fs",
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
