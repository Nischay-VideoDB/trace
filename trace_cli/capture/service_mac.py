"""macOS capture pipeline using the official VideoDB CaptureClient SDK.

Requires:
    pip install "videodb[capture]"
    pip install watchdog

The CaptureClient SDK ships macOS wheels and handles screen + mic natively.
On stop, the session is exported to a durable VideoDB video. The CLI reuses
that provider asset directly for indexing instead of downloading an HLS
manifest and uploading the same recording a second time.

Active window tracking uses osascript (built-in on macOS, no extra deps).
File save watching uses watchdog's FSEvents observer (native macOS kernel API).
"""
from __future__ import annotations

import asyncio
import logging
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

    @property
    def provider_video_id(self) -> str | None:
        return self._sdk_state.get("video_id")

    @property
    def capture_session_id(self) -> str | None:
        return self._sdk_state.get("cap_session_id")


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
    sdk_state["errors"] = error_holder

    def _run_sdk() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        sdk_state["loop"] = loop
        try:
            loop.run_until_complete(_sdk_start(sdk_state, ready, error_holder, mic))
        except Exception as e:  # noqa: BLE001
            error_holder.append(e)
            ready.set()
        finally:
            loop.close()

    t = threading.Thread(target=_run_sdk, name="videodb-capture-sdk", daemon=True)
    t.start()
    sdk_state["thread"] = t

    # Wait up to 30s for the SDK to become active.
    if not ready.wait(timeout=30.0):
        loop = sdk_state.get("loop")
        stop_event = sdk_state.get("stop_event")
        if loop and stop_event and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
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
    token = conn.generate_client_token(expires_in=600)
    cap_session = conn.create_capture_session(
        end_user_id="trace-user",
        collection_id="default",
        metadata={"app": "trace"},
    )
    sdk_state["cap_session_id"] = cap_session.id
    sdk_state["conn"] = conn

    client = CaptureClient(client_token=token)
    sdk_state["client"] = client

    screen_allowed = await client.request_permission("screen_capture")
    if screen_allowed is False:
        raise CaptureError("screen recording permission was denied")
    mic_allowed = False
    if mic:
        mic_allowed = await client.request_permission("microphone")
        if mic_allowed is False:
            log.warning("microphone permission denied; continuing with screen capture only")

    channels = await client.list_channels()
    display = channels.displays.default
    mic_ch = channels.mics.default if mic and mic_allowed is not False else None

    if display is None:
        raise CaptureError("no display capture channel is available")

    display.store = True
    display.is_primary = True
    if mic_ch:
        mic_ch.store = True

    selected = [ch for ch in [display, mic_ch] if ch]
    await client.start_session(
        capture_session_id=cap_session.id,
        channels=selected,
    )

    stop_event = asyncio.Event()
    sdk_state["stop_event"] = stop_event
    ready.set()

    # Block until stop_capture() triggers the event.
    await stop_event.wait()

    try:
        await client.stop_session()

        async def _await_flush() -> None:
            async for message in client.events():
                if isinstance(message, dict):
                    event_name = str(message.get("event") or message.get("name") or "")
                    payload = message.get("payload") or message.get("data") or {}
                else:
                    event_name = str(getattr(message, "event", ""))
                    payload = getattr(message, "payload", {})
                log.debug("VideoDB capture event=%s", event_name)
                if event_name in {"recording-complete", "recording:stopped", "recording_complete"}:
                    return
                if event_name == "error":
                    raise CaptureError(f"VideoDB capture recorder error: {payload}")

        try:
            await asyncio.wait_for(_await_flush(), timeout=30.0)
        except asyncio.TimeoutError as exc:
            raise CaptureError("capture recorder did not confirm media flush") from exc
    finally:
        await client.shutdown()
        sdk_state["stopped"] = True


def stop_capture(h: CaptureHandles, timeout: float = 120.0) -> tuple[Path | None, Path | None]:
    """Stop the SDK capture and wait for a durable VideoDB export."""
    sdk_state = h._sdk_state
    loop_thread: threading.Thread = sdk_state.get("thread")

    # Signal the async loop to stop.
    stop_event: asyncio.Event | None = sdk_state.get("stop_event")
    if stop_event:
        # Schedule the set() on the SDK's event loop.
        # We can't call stop_event.set() directly from another thread.
        loop = sdk_state.get("loop")
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        else:
            raise CaptureError("capture event loop is unavailable")

    # Wait for the SDK thread to finish.
    if loop_thread:
        loop_thread.join(timeout=timeout)
        if loop_thread.is_alive():
            raise CaptureError("VideoDB CaptureClient did not stop before timeout")

    if sdk_state.get("errors"):
        raise CaptureError(f"VideoDB CaptureClient failed: {sdk_state['errors'][0]}")

    # Export the session to a permanent video and download it.
    cap_session_id: str | None = sdk_state.get("cap_session_id")
    conn = sdk_state.get("conn")
    if conn and cap_session_id:
        try:
            video_id = _wait_for_exported_video(conn, cap_session_id, timeout=timeout)
            sdk_state["video_id"] = video_id
        except Exception as e:  # noqa: BLE001
            log.error("failed to download exported video: %s", e)
            raise CaptureError(f"export/download failed: {e}") from e
    else:
        raise CaptureError("no VideoDB connection or session id — cannot export")

    # Audio is muxed into the provider export. No local duplicate is needed.
    return None, None


def _wait_for_exported_video(conn, cap_session_id: str, timeout: float) -> str:
    """Trigger/poll CaptureSession.export() and return its permanent video id."""
    deadline = time.time() + timeout
    log.info("waiting for capture export (cap_session_id=%s)", cap_session_id)

    video_id: str | None = None
    while time.time() < deadline:
        try:
            session = conn.get_capture_session(cap_session_id)
            result = session.export()
            status = str(result.get("export_status") or "").lower()
            vid = result.get("video_id") or getattr(session, "exported_video_id", None)
            if status == "failed":
                raise CaptureError("VideoDB capture export failed")
            if status == "exported" and vid:
                video_id = str(vid)
                break
        except CaptureError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("capture export poll pending: %s", exc)
        time.sleep(2.0)

    if not video_id:
        raise CaptureError("timed out waiting for capture session export")

    log.info("capture exported to VideoDB video id=%s", video_id)
    return video_id


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
