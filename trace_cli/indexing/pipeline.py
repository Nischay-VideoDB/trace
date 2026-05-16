"""Post-stop indexing pipeline.

Steps (per .kiro design wave 5):
  1. Upload screen.mp4 to VideoDB (`coll.upload`).
  2. Index spoken words (`video.index_spoken_words`) -> transcript.
  3. Index scenes with custom classifier prompt (`video.index_scenes`).
  4. Fetch transcript, persist to transcript.json.
  5. Update metadata status -> indexed (or *_failed).

The custom-prompt scene index is the depth lever for visual classification;
its results feed the research classifier in timeline/builder.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trace_cli.session.models import SessionMetadata, Transcript, TranscriptSegment
from trace_cli.session.store import SessionStore
from trace_cli.utils.retry import retry_sync
from trace_cli.videodb.client import VideoDBClient, VideoDBError

log = logging.getLogger("trace.indexing")

SCENE_CLASSIFIER_PROMPT = (
    "Classify the foreground content of this clip into exactly one of these labels: "
    "code_editor, browser_docs, terminal, ai_assistant, other. "
    "Also extract any visible filenames, function names, or error messages. "
    "Reply in JSON: {\"label\": <one_label>, \"files\": [<filename>...], "
    "\"functions\": [<funcname>...], \"errors\": [<error_text>...], \"summary\": <one_sentence>}."
)


class IndexingError(Exception):
    pass


def _segments_from_video_transcript(video) -> list[TranscriptSegment]:
    """Read the spoken-word transcript off a freshly indexed Video.

    SDK exposes `video.get_transcript(segmenter=...)` which returns either a list of
    segment dicts {start, end, text} or a single string. We request sentence-level
    segmentation to give the timeline classifier meaningful chunks (word-level is
    too granular for the >= 3 words / >= 1s speech rule).
    """
    if not hasattr(video, "get_transcript"):
        return []
    try:
        from videodb import Segmenter
        raw = video.get_transcript(segmenter=Segmenter.sentence)
    except Exception:
        raw = video.get_transcript()
    if not raw:
        return []
    if isinstance(raw, str):
        return [TranscriptSegment(start_seconds=0.0, end_seconds=max(1.0, len(raw) / 15.0), text=raw)]
    segs: list[TranscriptSegment] = []
    for it in raw:
        try:
            start = float(it.get("start") or it.get("start_seconds") or 0.0)
            end = float(it.get("end") or it.get("end_seconds") or start + 1.0)
            text = str(it.get("text") or it.get("word") or "").strip()
            if end <= start:
                end = start + 0.5
            if text:
                segs.append(TranscriptSegment(start_seconds=start, end_seconds=end, text=text))
        except (TypeError, ValueError, KeyError):
            continue
    return segs


def _mux_audio_into_video(video_path: Path, audio_path: Path, *, out_path: Path) -> Path:
    """Mux audio.wav into video mp4 using ffmpeg. Returns out_path on success.

    VideoDB transcription needs an audio stream in the uploaded video; wf-recorder
    writes video-only mp4 while audio is captured by a parallel ffmpeg process.
    """
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(out_path),
    ]
    log.info("muxing audio into video: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise IndexingError(f"ffmpeg mux failed: {r.stderr[:500]}")
    return out_path


def run_indexing(session_id: str, *, store: SessionStore | None = None, scene_time: int = 10) -> SessionMetadata:
    """Upload mp4 + index spoken words + index scenes. Updates metadata."""
    store = store or SessionStore()
    meta = store.read_metadata(session_id)
    screen = store.screen_path(session_id)
    if not screen.exists() or screen.stat().st_size == 0:
        raise IndexingError(f"screen.mp4 missing or empty for session {session_id}")

    # Mux audio.wav into the mp4 so VideoDB can transcribe.
    audio = store.audio_path(session_id)
    upload_path = screen
    if audio.exists() and audio.stat().st_size > 0:
        muxed = screen.with_name("screen_av.mp4")
        try:
            upload_path = _mux_audio_into_video(screen, audio, out_path=muxed)
            log.info("muxed video+audio to %s (%d bytes)", upload_path, upload_path.stat().st_size)
        except IndexingError as e:
            log.warning("mux failed (%s); uploading video-only", e)

    client = VideoDBClient()

    # 1. Upload (retried because network is the most failure-prone here)
    log.info("uploading %s to VideoDB...", upload_path)
    try:
        video = retry_sync(
            lambda: client.upload_file(upload_path, name=f"trace-{session_id[:8]}"),
            max_attempts=3,
            base_delay=2.0,
        )
    except VideoDBError as e:
        store.update_metadata(session_id, status="indexing_failed")
        raise IndexingError(f"upload failed: {e}") from e
    log.info("uploaded video id=%s length=%s", video.id, getattr(video, "length", "?"))
    store.update_metadata(session_id, video_id=video.id, status="processing")

    # 2. Spoken word index (transcript)
    transcript_ok = True
    try:
        client.index_video_spoken(video)
    except VideoDBError as e:
        log.warning("spoken word index failed: %s", e)
        transcript_ok = False

    # 3. Scene index (classifier prompt). Capture index id for later search.
    scene_index_id: str | None = None
    try:
        scene_index_id = client.index_video_scenes(
            video,
            prompt=SCENE_CLASSIFIER_PROMPT,
            time_seconds=scene_time,
            frame_count=3,
        )
        log.info("scene index id=%s", scene_index_id)
    except VideoDBError as e:
        log.warning("scene index failed: %s", e)

    # 4. Persist transcript
    transcript = Transcript(session_id=session_id, segments=[])
    if transcript_ok:
        try:
            transcript.segments = _segments_from_video_transcript(video)
        except Exception as e:  # noqa: BLE001
            log.warning("transcript fetch failed: %s", e)
            transcript_ok = False
    store.transcript_path(session_id).write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    log.info("transcript: %d segments", len(transcript.segments))

    # 5. Stash scene index id for the timeline builder via metadata
    extra: dict[str, Any] = {}
    if scene_index_id:
        extra["scene_index_id"] = scene_index_id
    if not transcript_ok:
        extra["status"] = "transcription_failed"
    else:
        extra["status"] = "indexed"

    final = store.update_metadata(session_id, **extra)
    return final
