"""macOS capture pipeline using the official VideoDB CaptureClient SDK.

Requires:
    pip install "videodb[capture]"
    pip install watchdog

The CaptureClient SDK ships macOS wheels and handles screen + mic natively.
On stop, the session is exported to a VideoDB video — we download it locally
so the rest of the pipeline (indexing, timeline, PR video) works identically
to the Linux path.

Active window tracking uses osascript (built-in on macOS, no extra deps).
File save watching uses watchdog's FSEvents observer (native macOS kernel API).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("trace.capture.mac")


class CaptureError(Exception):
    pass


@dataclass
class CaptureHandles:
    """Mirrors the Linux CaptureHandles interface so cli.py needs no changes."""
    process: "FakeProcess"          # fake process — SDK manages the recorder
    output_path: Path
    started_at_unix: float
    audio_path: Path | None = None
    audio_proc: None = None
    # macOS-specific: hold references so GC doesn't kill them
    _sdk_state: dict = field(default_factory=dict)


class FakeProcess:
    """Stands in for subprocess.Popen so cli.py's poll() check works."""
    def poll(self) -> None:
        return None  # always "running"


# ---------------------------------------------------------------------------
# Capture start / stop
# ---------------------------------------------------------------------------

def start_capture(output_path: Path, *, fps: int = 30, mic: bool = True) -> CaptureHandles:
    """Start screen + mic capture via VideoDB CaptureClient SDK.

    The SDK streams directly to VideoDB. On stop we export and download the
    video to output_path so the rest of the pipeline is unchanged.
    """
    try:
        import videodb
        from videodb.capture import CaptureClient
    except ImportError as e:
        raise CaptureError(
            "videodb[capture] not installed. Run: pip install 'videodb[capture]'"
        ) from e

    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    audio_path = output_path.with_name("audio.wav")

    # Run the async SDK setup in a dedicated thread with its own event loop.
    sdk_state: dict = {}
    ready = threading.Event()
    error_holder: list[Exception] = []

    def _run_sdk() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_sdk_start(sdk_state, ready, error_holder, mic))
        except Exception as e:  # noqa: BLE001
            error_holder.append(e)
            ready.set()
        finally:
            # Keep loop alive — SDK needs it running for the duration of capture.
            # We block here until stop_capture() sets sdk_state["stop_event"].
            stop_ev: asyncio.Event = sdk_state.get("stop_event") or asyncio.Event()
            loop.run_until_complete(stop_ev.wait())
            loop.close()

    t = threading.Thread(target=_run_sdk, name="videodb-capture-sdk", daemon=True)
    t.start()
    sdk_state["thread"] = t

    # Wait up to 30s for the SDK to become active.
    if not ready.wait(timeout=30.0):
        raise CaptureError("VideoDB CaptureClient did not become active within 30s")
    if error_holder:
        raise CaptureError(f"VideoDB CaptureClient failed: {error_holder[0]}") from error_holder[0]

    log.info("VideoDB CaptureClient active (macOS)")
    handles = CaptureHandles(
        process=FakeProcess(),
        output_path=output_path,
        started_at_unix=time.time(),
        audio_path=audio_path,
        _sdk_state=sdk_state,
    )
    return handles


async def _sdk_start(
    sdk_state: dict,
    ready: threading.Event,
    error_holder: list,
    mic: bool,
) -> None:
    """Async coroutine: initialise SDK, start capture, signal ready."""
    import videodb
    from videodb.capture import CaptureClient

    conn = videodb.connect()
    token = conn.generate_client_token()
    cap_session = conn.create_capture_session(
        end_user_id="trace-user",
        collection_id="default",
        metadata={"app": "trace"},
    )
    sdk_state["cap_session_id"] = cap_session.id
    sdk_state["conn"] = conn

    client = CaptureClient(client_token=token)
    sdk_state["client"] = client

    await client.request_permission("screen_capture")
    if mic:
        await client.request_permission("microphone")

    channels = await client.list_channels()
    display = channels.displays.default
    mic_ch = channels.mics.default if mic else None

    if display:
        display.store = True
    if mic_ch:
        mic_ch.store = True

    selected = [ch for ch in [display, mic_ch] if ch]
    await client.start_capture_session(
        capture_session_id=cap_session.id,
        channels=selected,
        primary_video_channel_id=display.id if display else None,
    )

    stop_event = asyncio.Event()
    sdk_state["stop_event"] = stop_event
    ready.set()

    # Block until stop_capture() triggers the event.
    await stop_event.wait()

    await client.stop_capture()
    await client.shutdown()
    sdk_state["stopped"] = True


def stop_capture(h: CaptureHandles, timeout: float = 60.0) -> tuple[Path, Path | None]:
    """Stop the SDK capture, wait for export, download video to output_path."""
    sdk_state = h._sdk_state
    loop_thread: threading.Thread = sdk_state.get("thread")

    # Signal the async loop to stop.
    stop_event: asyncio.Event | None = sdk_state.get("stop_event")
    if stop_event:
        # Schedule the set() on the SDK's event loop.
        # We can't call stop_event.set() directly from another thread.
        import asyncio as _asyncio
        for _ in range(100):
            if loop_thread and loop_thread.is_alive():
                # Post to the loop via call_soon_threadsafe.
                # We need the loop object — stored during _run_sdk.
                _loop = sdk_state.get("loop")
                if _loop and not _loop.is_closed():
                    _loop.call_soon_threadsafe(stop_event.set)
                    break
            time.sleep(0.1)
        else:
            log.warning("could not signal SDK stop event; forcing")

    # Wait for the SDK thread to finish.
    if loop_thread:
        loop_thread.join(timeout=timeout)

    # Export the session to a permanent video and download it.
    cap_session_id: str | None = sdk_state.get("cap_session_id")
    conn = sdk_state.get("conn")
    if conn and cap_session_id:
        try:
            _download_exported_video(conn, cap_session_id, h.output_path, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            log.error("failed to download exported video: %s", e)
            raise CaptureError(f"export/download failed: {e}") from e
    else:
        raise CaptureError("no VideoDB connection or session id — cannot export")

    if not h.output_path.exists() or h.output_path.stat().st_size == 0:
        raise CaptureError(f"capture file empty or missing: {h.output_path}")

    # Audio is embedded in the exported mp4 — no separate wav needed.
    return h.output_path, None


def _download_exported_video(conn, cap_session_id: str, dest: Path, timeout: float) -> None:
    """Poll for capture_session.exported event then download the video."""
    import httpx

    deadline = time.time() + timeout
    log.info("waiting for capture_session.exported (cap_session_id=%s)", cap_session_id)

    video_id: str | None = None
    while time.time() < deadline:
        try:
            session = conn.get_capture_session(cap_session_id)
            # SDK may expose status or exported_video_id directly.
            vid = getattr(session, "exported_video_id", None)
            if vid:
                video_id = vid
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2.0)

    if not video_id:
        raise CaptureError("timed out waiting for capture session export")

    # Get the download URL from the video object.
    video = conn.get_collection().get_video(video_id)
    stream_url = getattr(video, "stream_url", None) or getattr(video, "url", None)
    if not stream_url:
        raise CaptureError(f"no download URL for video {video_id}")

    log.info("downloading exported video from %s", stream_url)
    with httpx.stream("GET", stream_url, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    log.info("downloaded %d bytes to %s", dest.stat().st_size, dest)


# ---------------------------------------------------------------------------
# macOS watchers
# ---------------------------------------------------------------------------

class WatchdogSaveWatcher(threading.Thread):
    """File save watcher using watchdog FSEvents (macOS native).

    Drop-in replacement for InotifyWatcher.
    Requires: pip install watchdog
    """

    _CODE_EXT = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
        ".java", ".kt", ".rb", ".php", ".swift", ".cs", ".sh", ".bash", ".zsh", ".fish",
        ".md", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".scss", ".vue",
        ".lua", ".ex", ".exs", ".clj", ".scala",
    }

    def __init__(self, session_id: str, store, watch_dir: Path) -> None:
        super().__init__(name=f"watchdog-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._dir = watch_dir
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("watchdog not installed; skipping file-save watcher. Run: pip install watchdog")
            return

        from trace_cli.session.models import SaveEvent

        class _Handler(FileSystemEventHandler):
            def __init__(self, sid: str, store, code_ext: set) -> None:
                self._sid = sid
                self._store = store
                self._code_ext = code_ext

            def on_closed(self, event):  # type: ignore[override]
                if event.is_directory:
                    return
                ext = Path(event.src_path).suffix.lower()
                if ext and ext not in self._code_ext:
                    return
                ev = SaveEvent(t_unix=time.time(), path=event.src_path, kind="close_write")
                try:
                    self._store.append_event(self._sid, "saves", ev)
                except Exception as e:  # noqa: BLE001
                    log.warning("save event write failed: %s", e)

        handler = _Handler(self._sid, self._store, self._CODE_EXT)
        observer = Observer()
        observer.schedule(handler, str(self._dir), recursive=True)
        observer.start()
        log.info("watchdog FSEvents observer started on %s", self._dir)
        try:
            while not self._stop.is_set():
                self._stop.wait(1.0)
        finally:
            observer.stop()
            observer.join()


class OsascriptWindowPoller(threading.Thread):
    """1 Hz active-window poll via osascript (built-in on macOS).

    Drop-in replacement for HyprctlPoller.
    No extra dependencies — osascript is always available on macOS.
    """

    def __init__(self, session_id: str, store, interval: float = 1.0) -> None:
        super().__init__(name=f"osascript-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._interval = interval
        self._stop = threading.Event()
        self._last_key: tuple[str, str] | None = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from trace_cli.session.models import WindowEvent

        # AppleScript to get frontmost app name and window title.
        script = (
            'tell application "System Events"\n'
            '  set frontApp to name of first application process whose frontmost is true\n'
            'end tell\n'
            'tell application frontApp\n'
            '  try\n'
            '    set winTitle to name of front window\n'
            '  on error\n'
            '    set winTitle to ""\n'
            '  end try\n'
            'end tell\n'
            'return frontApp & "|" & winTitle'
        )
        while not self._stop.is_set():
            try:
                out = subprocess.check_output(
                    ["osascript", "-e", script],
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    text=True,
                ).strip()
                if "|" in out:
                    cls, title = out.split("|", 1)
                else:
                    cls, title = out, ""
                key = (cls.strip(), title.strip())
                if key != self._last_key and (cls or title):
                    ev = WindowEvent(t_unix=time.time(), cls=cls.strip(), title=title.strip())
                    self._store.append_event(self._sid, "windows", ev)
                    self._last_key = key
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
            except Exception as e:  # noqa: BLE001
                log.debug("osascript poll error: %s", e)
            self._stop.wait(self._interval)
