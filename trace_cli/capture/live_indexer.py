"""Pseudo-live VideoDB indexing during capture.

Every `chunk_seconds` (default 15s) while a session is recording:
  1. Snapshot the current screen.mp4 + audio.wav.
  2. Cut a chunk via ffmpeg covering the new window since last snapshot.
  3. Upload chunk to VideoDB.
  4. Kick off index_spoken_words and index_scenes on the chunk.
  5. Persist the chunk's metadata in events_chunks.jsonl so the timeline
     builder can pull live scene descriptions and the Q&A path can search
     across all chunks.

This lights up the VideoDB live ingest surface without needing a public
RTSP URL (which would require cloudflared/ngrok account auth).

The full final video still gets uploaded once at trace stop (existing
batch path) so we keep one canonical Video for PR video assembly and
decision replay. Chunks are supplementary, used for search and live
scene descriptions.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from trace_cli.session.store import SessionStore
from trace_cli.videodb.client import VideoDBClient

log = logging.getLogger("trace.live_indexer")

LIVE_SCENE_PROMPT = (
    "Describe what is on screen in 1 sentence. "
    "Include the foreground app (terminal, browser, code editor, ai_assistant, other), "
    "any visible filenames, and any visible error messages."
)


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


class LiveIndexer(threading.Thread):
    """Background loop: cut chunks of the in-progress capture, upload, index."""

    def __init__(
        self,
        session_id: str,
        store: SessionStore,
        screen_path: Path,
        audio_path: Path | None,
        *,
        chunk_seconds: int = 15,
        min_chunk_seconds: int = 8,
    ) -> None:
        super().__init__(name=f"live-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._screen = screen_path
        self._audio = audio_path
        self._chunk_seconds = chunk_seconds
        self._min_chunk_seconds = min_chunk_seconds
        self._stop = threading.Event()
        self._last_cursor = 0.0
        self._client: VideoDBClient | None = None
        self._chunks_dir = screen_path.parent / "chunks"
        self._chunks_dir.mkdir(exist_ok=True, mode=0o700)

    def stop(self) -> None:
        self._stop.set()

    def _probe_duration(self, path: Path) -> float:
        if not _have_ffmpeg():
            return 0.0
        try:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)],
                stderr=subprocess.DEVNULL, timeout=4.0,
            )
            return float(out.decode().strip() or 0.0)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            return 0.0

    def _cut_chunk(self, start: float, end: float) -> Path | None:
        """ffmpeg cut [start, end] from screen.mp4 + audio.wav into one chunk mp4."""
        if end - start < self._min_chunk_seconds:
            return None
        out = self._chunks_dir / f"chunk_{int(start):05d}_{int(end):05d}.mp4"
        # Build a single ffmpeg call: input video + audio, slice both, mux.
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
               "-i", str(self._screen)]
        if self._audio and self._audio.exists():
            cmd += ["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(self._audio),
                    "-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                "-c:a", "aac", "-ar", "16000", "-ac", "1",
                str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            log.warning("ffmpeg chunk cut failed: %s", r.stderr[-200:])
            return None
        return out

    def _process_chunk(self, chunk_path: Path, t_start: float, t_end: float) -> None:
        if self._client is None:
            try:
                self._client = VideoDBClient()
            except Exception as e:  # noqa: BLE001
                log.warning("VideoDB connect failed; skipping live indexing (%s)", e)
                return

        try:
            video = self._client.upload_file(chunk_path, name=f"{self._sid[:8]}-chunk-{int(t_start)}")
        except Exception as e:  # noqa: BLE001
            log.warning("chunk upload failed (%s)", e)
            return

        scene_idx_id: str | None = None
        try:
            scene_idx_id = self._client.index_video_scenes(
                video, prompt=LIVE_SCENE_PROMPT, time_seconds=5, frame_count=2,
            )
        except Exception as e:  # noqa: BLE001
            log.info("chunk scene index skipped (%s)", e)

        try:
            self._client.index_video_spoken(video)
        except Exception as e:  # noqa: BLE001
            log.info("chunk spoken-word index skipped (%s)", e)

        record = {
            "t_start": t_start,
            "t_end": t_end,
            "video_id": video.id,
            "scene_index_id": scene_idx_id,
            "chunk_path": str(chunk_path),
            "indexed_at_unix": time.time(),
        }
        self._store.append_event(self._sid, "chunks", record)
        log.info("live chunk indexed: [%.0f-%.0fs] video_id=%s", t_start, t_end, video.id)

    def run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._chunk_seconds)
            if self._stop.is_set():
                break
            cur_dur = self._probe_duration(self._screen)
            if cur_dur - self._last_cursor < self._min_chunk_seconds:
                continue
            t_start, t_end = self._last_cursor, cur_dur
            chunk = self._cut_chunk(t_start, t_end)
            if chunk is None:
                continue
            self._last_cursor = t_end
            # Process in a thread so we don't block the cut loop on network IO.
            threading.Thread(
                target=self._process_chunk,
                args=(chunk, t_start, t_end),
                name=f"chunk-{int(t_start)}",
                daemon=True,
            ).start()
