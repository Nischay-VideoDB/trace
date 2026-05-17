"""PR video render via videodb.editor.Timeline.

Strategy: generate ALL narration as ONE audio asset (one TTS call = one voice,
guaranteed consistent). Concatenate scripts with 1-second pause markers between
clips. Place that single audio on the audio track starting at offset 0.

Video track: sequential clips, each trimmed to match its narration segment length.
Audio track: single asset starting at 0, plays through entire timeline.

Clip durations are computed from per-clip narration char-count ratios so video
and audio stay in sync without per-clip TTS length measurement.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from videodb.editor import (
    AudioAsset,
    Background,
    Clip,
    Font,
    Position,
    TextAsset,
    Timeline,
    Track,
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

# Chars-per-second estimate for OmniVoice at normal speaking pace.
_CPS = 16.0
# Pause inserted between clips in the combined script (seconds equivalent).
_PAUSE_CHARS = int(_CPS * 1.0)  # ~1s pause
_PAUSE_TEXT = " ... "  # short pause marker OmniVoice handles naturally


def _badge_text(sc: SelectedClip) -> str:
    label = _CATEGORY_BADGE.get(sc.category, sc.category.upper())
    if sc.file_path:
        return f"trace - {label} - {os.path.basename(sc.file_path)}"
    return f"trace - {label}"


@dataclass
class RenderResult:
    hls_url: str
    narration_text: str
    narration_asset_ids: list[str]
    clip_count: int
    total_seconds: float


def render(
    client: VideoDBClient,
    video_id: str,
    clips: list[SelectedClip],
    per_clip_scripts: list[str],
    *,
    voice: str = "Default",
    source_volume: float = 0.0,
) -> RenderResult:
    if not clips or not per_clip_scripts:
        raise ValueError("clips and per_clip_scripts must be non-empty")
    if len(clips) != len(per_clip_scripts):
        raise ValueError(f"clip/script count mismatch: {len(clips)} vs {len(per_clip_scripts)}")

    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("source video length: %.3fs", video_length)

    # 1. Combine all scripts into ONE TTS call — guarantees single consistent voice.
    #    Segments separated by pause marker so OmniVoice breathes between clips.
    combined_script = _PAUSE_TEXT.join(per_clip_scripts)
    log.info("combined narration: %d chars across %d clips", len(combined_script), len(per_clip_scripts))

    audio_id = ""
    audio_total_len = 0.0
    try:
        audio = client.generate_voice(text=combined_script, voice=voice)
        audio_id = getattr(audio, "id", "")
        audio_total_len = float(getattr(audio, "length", 0.0) or 0.0)
        log.info("combined narration audio: id=%s len=%.2fs", audio_id, audio_total_len)
    except Exception as e:  # noqa: BLE001
        log.warning("generate_voice failed (%s); building silent video", e)

    # 2. Estimate per-clip audio duration proportional to char count.
    #    pause_chars added between each pair of clips.
    seg_chars = [len(s) for s in per_clip_scripts]
    pause_chars = _PAUSE_CHARS
    total_chars = sum(seg_chars) + pause_chars * (len(seg_chars) - 1)

    if audio_total_len > 0 and total_chars > 0:
        cps_actual = audio_total_len / total_chars
    else:
        cps_actual = 1.0 / _CPS

    per_clip_audio_dur: list[float] = []
    for i, sc in enumerate(seg_chars):
        chars = sc + (pause_chars if i < len(seg_chars) - 1 else 0)
        per_clip_audio_dur.append(chars * cps_actual)

    log.info(
        "per-clip durations (estimated): %s",
        [f"{d:.1f}s" for d in per_clip_audio_dur],
    )

    # 3. Build timeline: video clips trimmed to match estimated audio segment lengths.
    tl = Timeline(client._conn)
    video_track = Track(z_index=0)
    audio_track = Track(z_index=1)
    badge_track = Track(z_index=2)

    total_float = 0.0
    placed = 0
    for i, (sc, aud_dur) in enumerate(zip(clips, per_clip_audio_dur)):
        src_start = max(0.0, sc.start)
        src_end = min(video_length - 0.05 if video_length > 0 else sc.end, sc.end)
        src_dur = max(0.5, src_end - src_start)

        # Video clip duration = estimated audio duration for this segment.
        output_dur = max(2.0, aud_dur)

        # If audio longer than available source span, extend into recording.
        if output_dur > src_dur and video_length > 0:
            src_end = min(video_length - 0.05, src_start + output_dur)
        elif output_dur < src_dur:
            src_end = src_start + output_dur

        if output_dur < 0.5:
            log.warning("clip %d: output_dur=%.2f too short; skipping", i, output_dur)
            continue

        cursor = int(round(total_float))

        v_asset = VideoAsset(id=video_id, start=src_start, volume=source_volume)
        v_clip = Clip(asset=v_asset, duration=output_dur)
        video_track.add_clip(cursor, v_clip)

        try:
            badge = TextAsset(
                text=_badge_text(clips[i]),
                font=Font(family="Clear Sans", size=32, color="#FFFFFF", opacity=1.0),
                background=Background(width=0.0, height=0.0, color="#000000", opacity=0.7),
            )
            badge_clip = Clip(asset=badge, duration=output_dur, position=Position.top_left, opacity=0.9)
            badge_track.add_clip(cursor, badge_clip)
        except Exception as e:  # noqa: BLE001
            log.debug("badge skipped for clip %d: %s", i, e)

        total_float += output_dur
        placed += 1

    # Place single audio asset at position 0 — spans entire timeline.
    if audio_id and audio_total_len > 0:
        a_asset = AudioAsset(id=audio_id, start=0, volume=1.0)
        a_clip = Clip(asset=a_asset, duration=audio_total_len)
        audio_track.add_clip(0, a_clip)

    tl.add_track(video_track)
    tl.add_track(audio_track)
    tl.add_track(badge_track)

    log.info(
        "timeline: %d clips placed, total video=%.1fs, audio=%.1fs",
        placed, total_float, audio_total_len,
    )

    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"timeline.generate_stream failed: {e}") from e

    return RenderResult(
        hls_url=url,
        narration_text=combined_script,
        narration_asset_ids=[audio_id] if audio_id else [],
        clip_count=placed,
        total_seconds=total_float,
    )
