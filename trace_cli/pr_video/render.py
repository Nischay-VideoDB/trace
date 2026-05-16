"""PR video render with per-clip narration overlays.

For each clip we generate a TTS audio asset and place it at the running
offset on the timeline. Clips and narration stay aligned: what you hear at
time T is what you see at time T.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from trace_cli.pr_video.selector import Clip
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
    clips: list[Clip],
    per_clip_scripts: list[str],
    *,
    voice: str = "Default",
) -> RenderResult:
    """Build Timeline of clips inline with per-clip narration overlays.

    Each clip's narration audio is generated, its length measured, and the
    clip duration adjusted to match. The result: at every second of the video,
    the narration corresponds to what is on screen.
    """
    if not clips or not per_clip_scripts:
        raise ValueError("clips and per_clip_scripts must be non-empty")
    if len(clips) != len(per_clip_scripts):
        raise ValueError(f"clip/script count mismatch: {len(clips)} vs {len(per_clip_scripts)}")

    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("source video length: %.3fs", video_length)

    # 1. Synthesize all narration chunks first so we know their durations.
    narration_assets: list[tuple[str, float]] = []
    for i, script in enumerate(per_clip_scripts):
        try:
            audio = client.generate_voice(text=script, voice=voice)
            aid = getattr(audio, "id", "")
            alen = float(getattr(audio, "length", 0.0) or 0.0)
            log.info("clip %d narration: id=%s len=%.2fs (%d chars)", i, aid, alen, len(script))
            narration_assets.append((aid, alen))
        except Exception as e:  # noqa: BLE001
            log.warning("generate_voice failed clip %d (%s); skipping narration for clip", i, e)
            narration_assets.append(("", 0.0))

    # 2. Assemble Timeline: for each clip, decide actual clip duration to match
    #    its narration length. Then inline the clip, and overlay narration at
    #    the running cursor.
    tl = client.build_timeline()
    cursor = 0.0
    total = 0.0
    for c, (aid, alen) in zip(clips, narration_assets):
        # Default clip span clamped to video length.
        clip_end = min(c.end, video_length - 0.05) if video_length > 0 else c.end
        clip_start = max(0.0, min(c.start, clip_end - 0.5))
        clip_dur = clip_end - clip_start

        # Target the larger of (narration length + 0.5 buffer, clip_dur), so
        # narration always finishes before the clip cuts. If narration is
        # shorter than clip_dur, trim clip to narration length + small tail.
        if alen > 0:
            target_dur = max(alen + 0.5, 2.0)
            if target_dur < clip_dur:
                # Center the trim around the original midpoint when possible.
                mid = (clip_start + clip_end) / 2
                new_start = max(clip_start, mid - target_dur / 2)
                new_end = min(clip_end, new_start + target_dur)
                new_start = max(clip_start, new_end - target_dur)
                clip_start, clip_end = new_start, new_end
            elif target_dur > clip_dur:
                # Try to extend within the source video.
                extra = target_dur - clip_dur
                new_end = min(video_length - 0.05, clip_end + extra)
                clip_end = new_end
                if clip_end - clip_start < target_dur:
                    new_start = max(0.0, clip_start - (target_dur - (clip_end - clip_start)))
                    clip_start = new_start
            clip_dur = clip_end - clip_start

        if clip_dur < 0.5:
            log.warning("skipping clip [%.2f-%.2f]: too short after sizing", c.start, c.end)
            continue

        va = client.video_asset(video_id=video_id, start=clip_start, end=clip_end)
        tl.add_inline(va)

        if aid:
            audio_asset = client.audio_asset(
                audio_id=aid,
                disable_other_tracks=True,
                fade_in=0,
                fade_out=0,
            )
            tl.add_overlay(int(cursor), audio_asset)

        cursor += clip_dur
        total += clip_dur

    if total == 0:
        raise RuntimeError("all clips were skipped during assembly")

    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"timeline.generate_stream failed: {e}") from e

    return RenderResult(
        hls_url=url,
        narration_text="\n---\n".join(per_clip_scripts),
        narration_asset_ids=[a for a, _ in narration_assets if a],
        clip_count=len(clips),
        total_seconds=total,
    )
