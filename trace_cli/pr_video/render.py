"""PR video render via the modern videodb.editor.Timeline track model.

Builds two tracks:
  video track (z=0): VideoAsset Clips placed sequentially at integer offsets.
  audio track (z=1): narration AudioAsset Clips placed at the same offsets.

Clip durations are floats so the visible runtime matches narration audio
length down to fractional seconds. Source audio is ducked to 0.15 volume
under the narration so typing noises and small cues remain audible without
competing with the voiceover.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from videodb.editor import (
    AudioAsset,
    Clip,
    Timeline,
    Track,
    TrackItem,
    VideoAsset,
)

from trace_cli.pr_video.selector import Clip as SelectedClip
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.pr_video.render")


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
    source_volume: float = 0.15,
) -> RenderResult:
    if not clips or not per_clip_scripts:
        raise ValueError("clips and per_clip_scripts must be non-empty")
    if len(clips) != len(per_clip_scripts):
        raise ValueError(f"clip/script count mismatch: {len(clips)} vs {len(per_clip_scripts)}")

    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("source video length: %.3fs", video_length)

    # 1. TTS every chunk first; record audio asset id and length.
    narration: list[tuple[str, float]] = []
    for i, script in enumerate(per_clip_scripts):
        try:
            audio = client.generate_voice(text=script, voice=voice)
            aid = getattr(audio, "id", "")
            alen = float(getattr(audio, "length", 0.0) or 0.0)
            log.info("clip %d narration: id=%s len=%.2fs (%d chars)", i, aid, alen, len(script))
            narration.append((aid, alen))
        except Exception as e:  # noqa: BLE001
            log.warning("generate_voice failed clip %d (%s)", i, e)
            narration.append(("", 0.0))

    # 2. Decide clip duration per item.
    # Rule: video clip duration = max(source_dur, narration_len + 0.5).
    # If narration longer than available source span, extend clip end within source.
    plans: list[tuple[float, float, float]] = []  # (src_start, src_end, output_dur)
    for sc, (_aid, alen) in zip(clips, narration):
        src_start = max(0.0, sc.start)
        src_end = min(video_length - 0.05 if video_length > 0 else sc.end, sc.end)
        src_dur = max(0.5, src_end - src_start)

        target_dur = max(src_dur, alen + 0.5) if alen > 0 else src_dur
        # Try to fit target_dur within source. If source span too short, extend
        # src_end up to video_length; if narration still longer, just let
        # source loop or freeze on last frame (output_dur dictates timeline).
        if alen > 0 and alen + 0.5 > src_dur and video_length > 0:
            extend = (alen + 0.5) - src_dur
            new_end = min(video_length - 0.05, src_end + extend)
            src_end = new_end
            src_dur = src_end - src_start

        plans.append((src_start, src_end, target_dur))

    # 3. Build tracks.
    tl = Timeline(client._conn)
    video_track = Track(z_index=0)
    audio_track = Track(z_index=1)

    cursor_int = 0  # Track.add_clip takes integer start
    cursor_float = 0.0  # cumulative float for narration alignment
    for i, ((src_start, src_end, output_dur), (aid, alen)) in enumerate(zip(plans, narration)):
        if output_dur < 0.5:
            log.warning("clip %d: output_dur=%.2f too short; skipping", i, output_dur)
            continue

        # Place video clip.
        v_asset = VideoAsset(id=video_id, start=src_start, volume=source_volume)
        v_clip = Clip(asset=v_asset, duration=output_dur)
        video_track.add_clip(cursor_int, v_clip)

        # Place narration audio clip at same start on audio track.
        if aid:
            a_asset = AudioAsset(id=aid, start=0, volume=1.0)
            a_clip = Clip(asset=a_asset, duration=alen)
            audio_track.add_clip(cursor_int, a_clip)

        cursor_float += output_dur
        cursor_int = int(round(cursor_float))

    tl.add_track(video_track)
    tl.add_track(audio_track)

    log.info(
        "timeline: %d clips, total runtime %.1fs (video=%d items, audio=%d items)",
        len(plans), cursor_float, len(video_track.clips), len(audio_track.clips),
    )

    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"timeline.generate_stream failed: {e}") from e

    return RenderResult(
        hls_url=url,
        narration_text="\n---\n".join(per_clip_scripts),
        narration_asset_ids=[a for a, _ in narration if a],
        clip_count=len(plans),
        total_seconds=cursor_float,
    )
