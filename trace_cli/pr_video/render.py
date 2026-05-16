"""PR video render: synthesize narration TTS, assemble VideoDB Timeline, return HLS URL.

Uses VideoDB-hosted TTS (`coll.generate_voice`) and `videodb.timeline.Timeline`
with VideoAsset (inline clips) plus AudioAsset (narration overlay).
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
    narration_asset_id: str | None
    clip_count: int
    total_seconds: float


def render(
    client: VideoDBClient,
    video_id: str,
    clips: list[Clip],
    narration_text: str,
    *,
    voice: str = "Default",
) -> RenderResult:
    """Build Timeline with clips inline + narration audio overlay; return HLS URL."""
    if not clips:
        raise ValueError("no clips to render")

    # 1. TTS narration via VideoDB
    log.info("synthesizing narration via VideoDB generate_voice (%d chars)", len(narration_text))
    audio_asset = None
    audio_id: str | None = None
    try:
        audio = client.generate_voice(text=narration_text, voice=voice)
        audio_id = getattr(audio, "id", None)
    except Exception as e:  # noqa: BLE001
        log.warning("generate_voice failed (%s); proceeding without narration audio", e)

    # 2. Assemble Timeline. VideoDB rejects end > video.length; fetch length and clamp.
    video = client.get_video(video_id)
    video_length = float(getattr(video, "length", 0.0) or 0.0)
    log.info("video length per VideoDB: %.3fs", video_length)
    tl = client.build_timeline()
    total = 0.0
    for c in clips:
        end = min(c.end, video_length - 0.05) if video_length > 0 else c.end
        start = max(0.0, min(c.start, end - 0.5))
        if end - start < 0.5:
            log.warning("skipping clip [%.2f-%.2f]: too short after clamp", c.start, c.end)
            continue
        va = client.video_asset(video_id=video_id, start=start, end=end)
        tl.add_inline(va)
        total += end - start

    if audio_id:
        audio_asset = client.audio_asset(audio_id=audio_id, disable_other_tracks=True, fade_in=1, fade_out=1)
        tl.add_overlay(0, audio_asset)

    # 3. Render to HLS
    try:
        url = tl.generate_stream()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"timeline.generate_stream failed: {e}") from e

    return RenderResult(
        hls_url=url,
        narration_text=narration_text,
        narration_asset_id=audio_id,
        clip_count=len(clips),
        total_seconds=total,
    )
