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

import os

from videodb.editor import (
    AudioAsset,
    Background,
    Clip,
    Font,
    Position,
    TextAsset,
    Timeline,
    Track,
    TrackItem,
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


def _badge_text(sc: SelectedClip) -> str:
    label = _CATEGORY_BADGE.get(sc.category, sc.category.upper())
    if sc.file_path:
        return f"trace - {label} - {os.path.basename(sc.file_path)}"
    return f"trace - {label}"

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
    source_volume: float = 0.0,
) -> RenderResult:
    if not clips or not per_clip_scripts:
        raise ValueError("clips and per_clip_scripts must be non-empty")
    if len(clips) != len(per_clip_scripts):
        raise ValueError(f"clip/script count mismatch: {len(clips)} vs {len(per_clip_scripts)}")

    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("source video length: %.3fs", video_length)

    # 1. TTS every chunk in parallel; record audio asset id and length.
    # Long sessions (10+ clips) get a 5x speedup vs serial.
    from concurrent.futures import ThreadPoolExecutor

    def _tts_one(idx_script: tuple[int, str]) -> tuple[int, str, float]:
        i, script = idx_script
        try:
            audio = client.generate_voice(text=script, voice=voice)
            aid = getattr(audio, "id", "")
            alen = float(getattr(audio, "length", 0.0) or 0.0)
            log.info("clip %d narration: id=%s len=%.2fs (%d chars)", i, aid, alen, len(script))
            return i, aid, alen
        except Exception as e:  # noqa: BLE001
            log.warning("generate_voice failed clip %d (%s)", i, e)
            return i, "", 0.0

    narration_raw: list[tuple[int, str, float] | None] = [None] * len(per_clip_scripts)
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(per_clip_scripts)))) as ex:
        for result in ex.map(_tts_one, enumerate(per_clip_scripts)):
            narration_raw[result[0]] = result
    narration: list[tuple[str, float]] = [(r[1], r[2]) if r else ("", 0.0) for r in narration_raw]

    # 2. Decide clip duration per item.
    # Rule: video clip duration = max(source_dur, narration_len + 0.5).
    # If narration longer than available source span, extend clip end within source.
    plans: list[tuple[float, float, float]] = []  # (src_start, src_end, output_dur)
    for sc, (_aid, alen) in zip(clips, narration):
        src_start = max(0.0, sc.start)
        src_end = min(video_length - 0.05 if video_length > 0 else sc.end, sc.end)
        src_dur = max(0.5, src_end - src_start)

        # Tail buffer 0.1s only. Make video clip match narration length when narration
        # exists; ignore raw source clip duration so we never show dead air.
        if alen > 0:
            target_dur = alen + 0.1
        else:
            target_dur = src_dur

        # If narration is longer than the source span, extend src_end into the
        # rest of the recording so we have video to show.
        if alen > 0 and target_dur > src_dur and video_length > 0:
            extend = target_dur - src_dur
            new_end = min(video_length - 0.05, src_end + extend)
            src_end = new_end
            src_dur = src_end - src_start
        elif alen > 0 and target_dur < src_dur:
            # Narration shorter than source span: trim source to match.
            src_end = src_start + target_dur

        plans.append((src_start, src_end, target_dur))

    # 3. Build tracks.
    tl = Timeline(client._conn)
    video_track = Track(z_index=0)
    audio_track = Track(z_index=1)
    badge_track = Track(z_index=2)

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

        # Badge overlay: category + filename at top-left throughout clip.
        try:
            badge = TextAsset(
                text=_badge_text(clips[i]),
                font=Font(family="Clear Sans", size=32, color="#FFFFFF", opacity=1.0),
                background=Background(width=0.0, height=0.0, color="#000000", opacity=0.7),
            )
            badge_clip = Clip(asset=badge, duration=output_dur, position=Position.top_left, opacity=0.9)
            badge_track.add_clip(cursor_int, badge_clip)
        except Exception as e:  # noqa: BLE001
            log.debug("badge skipped for clip %d: %s", i, e)

        cursor_float += output_dur
        cursor_int = int(round(cursor_float))

    tl.add_track(video_track)
    tl.add_track(audio_track)
    tl.add_track(badge_track)

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
