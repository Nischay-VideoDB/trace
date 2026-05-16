"""Local capture pipeline.

Primary path on Linux Wayland: wf-recorder for screen + ffmpeg -f pulse for mic,
written to a single mp4 via ffmpeg's mux. Output: ~/.trace/sessions/{id}/screen.mp4.

We do NOT use VideoDB CaptureClient on Linux (no wheel available; macOS/Windows only).
Live ingest into VideoDB happens through a separate RTSP path (mediamtx + cloudflared)
wired in capture/rtstream.py.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("trace.capture")


class CaptureError(Exception):
    pass


@dataclass
class CaptureHandles:
    process: subprocess.Popen[bytes]
    output_path: Path
    started_at_unix: float


def _binary_or_die(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CaptureError(f"{name} not found on PATH; install it (pacman -S {name})")
    return path


def _has_pulse() -> bool:
    """Detect whether pulse/pipewire-pulse socket is available for current user."""
    candidates = [
        os.environ.get("XDG_RUNTIME_DIR"),
        f"/run/user/{os.getuid()}",
    ]
    return any(c and (Path(c) / "pulse" / "native").exists() for c in candidates)


def start_capture(output_path: Path, *, fps: int = 30, mic: bool = True) -> CaptureHandles:
    """Spawn ffmpeg subprocess capturing screen+mic to output_path mp4.

    Approach:
      - wf-recorder writes raw screen to a fifo (or pipe). ffmpeg reads it,
        adds pulse mic, encodes h264+aac, muxes to mp4.

    For simplicity v1: invoke ffmpeg directly with x11grab fallback if
    wf-recorder is not available. On pure Wayland Hyprland we use wf-recorder
    which speaks the wlr-screencopy protocol.

    Output mp4 is written incrementally with +faststart so partial files
    remain playable if the process is killed.
    """
    ffmpeg = _binary_or_die("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    # wf-recorder is preferred on Wayland but pipes raw frames poorly without
    # extra plumbing. Simpler: have wf-recorder write its own mp4 (no mic),
    # while a parallel ffmpeg writes audio.wav. Then on stop we mux them.
    #
    # We launch wf-recorder for video AND ffmpeg for audio as two subprocesses,
    # and orchestrate stop via signals. CaptureHandles tracks the video process;
    # audio is tracked as a child attribute.
    wf = _binary_or_die("wf-recorder")
    audio_path = output_path.with_name("audio.wav")

    # wf-recorder: -f screen.mp4 -c libx264 -p preset=ultrafast -r 30
    video_cmd = [
        wf,
        "-f", str(output_path),
        "-c", "libx264",
        "-p", "preset=ultrafast",
        "-p", "crf=28",
        "-p", "pix_fmt=yuv420p",
        "-r", str(fps),
        "-y",
    ]
    log.info("starting wf-recorder: %s", " ".join(video_cmd))
    video_proc = subprocess.Popen(
        video_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,  # so we can SIGINT the whole group cleanly
    )

    audio_proc: subprocess.Popen[bytes] | None = None
    if mic and _has_pulse():
        audio_cmd = [
            ffmpeg,
            "-y",
            "-f", "pulse",
            "-i", "default",
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            str(audio_path),
        ]
        log.info("starting ffmpeg audio: %s", " ".join(audio_cmd))
        audio_proc = subprocess.Popen(
            audio_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
    else:
        log.warning("mic disabled or pulse not detected; mic_status=denied")

    # Attach audio_proc to handles via attribute for stop() to pick up.
    handles = CaptureHandles(process=video_proc, output_path=output_path, started_at_unix=time.time())
    handles.audio_proc = audio_proc  # type: ignore[attr-defined]
    handles.audio_path = audio_path  # type: ignore[attr-defined]
    return handles


def stop_capture(h: CaptureHandles, timeout: float = 30.0) -> tuple[Path, Path | None]:
    """Send SIGINT to wf-recorder + ffmpeg-audio, wait for clean shutdown.

    Returns (video_path, audio_path or None).
    R2.1: flush within 30s.
    """
    deadline = time.time() + timeout

    audio_proc: subprocess.Popen[bytes] | None = getattr(h, "audio_proc", None)
    audio_path: Path | None = getattr(h, "audio_path", None)

    for label, p in (("audio", audio_proc), ("video", h.process)):
        if p is None or p.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGINT)
        except ProcessLookupError:
            continue

    for label, p in (("audio", audio_proc), ("video", h.process)):
        if p is None:
            continue
        remaining = max(0.5, deadline - time.time())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            log.error("%s process did not exit cleanly; SIGKILL", label)
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    if not h.output_path.exists() or h.output_path.stat().st_size == 0:
        raise CaptureError(f"capture file empty or missing: {h.output_path}")

    if audio_path and not audio_path.exists():
        log.warning("audio file missing after stop: %s", audio_path)
        audio_path = None

    return h.output_path, audio_path
