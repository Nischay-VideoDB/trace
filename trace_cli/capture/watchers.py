"""Background watchers: inotify file saves + hyprctl active window poll."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from trace_cli.session.models import SaveEvent, WindowEvent
from trace_cli.session.store import SessionStore

log = logging.getLogger("trace.watchers")

_CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
    ".java", ".kt", ".rb", ".php", ".swift", ".cs", ".sh", ".bash", ".zsh", ".fish",
    ".md", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".scss", ".vue",
    ".lua", ".ex", ".exs", ".clj", ".scala",
}


class InotifyWatcher(threading.Thread):
    """Streams `inotifywait -m` output into events_saves.jsonl."""

    def __init__(self, session_id: str, store: SessionStore, watch_dir: Path) -> None:
        super().__init__(name=f"inotify-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._dir = watch_dir
        self._stop = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass

    def run(self) -> None:
        bin_path = shutil.which("inotifywait")
        if not bin_path:
            log.warning("inotifywait not found; skipping file-save watcher")
            return
        cmd = [
            bin_path,
            "-m", "-r", "-q",
            "-e", "close_write",
            "--format", "%T|%w%f",
            "--timefmt", "%s",
            str(self._dir),
        ]
        log.info("inotifywait: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as e:
            log.error("failed to start inotifywait: %s", e)
            return
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            line = line.strip()
            if "|" not in line:
                continue
            ts_str, path = line.split("|", 1)
            try:
                ts = float(ts_str)
            except ValueError:
                continue
            ext = Path(path).suffix.lower()
            if ext and ext not in _CODE_EXT:
                continue
            ev = SaveEvent(t_unix=ts, path=path, kind="close_write")
            try:
                self._store.append_event(self._sid, "saves", ev)
            except Exception as e:  # noqa: BLE001
                log.warning("save event write failed: %s", e)


class HyprctlPoller(threading.Thread):
    """1 Hz active-window poll via hyprctl."""

    def __init__(self, session_id: str, store: SessionStore, interval: float = 1.0) -> None:
        super().__init__(name=f"hyprctl-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._interval = interval
        self._stop = threading.Event()
        self._last_key: tuple[str, str] | None = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        bin_path = shutil.which("hyprctl")
        if not bin_path:
            log.warning("hyprctl not found; skipping window watcher")
            return
        while not self._stop.is_set():
            try:
                out = subprocess.check_output(
                    [bin_path, "activewindow", "-j"],
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                )
                data = json.loads(out)
                cls = str(data.get("class", "") or "")
                title = str(data.get("title", "") or "")
                key = (cls, title)
                if key != self._last_key and (cls or title):
                    ev = WindowEvent(t_unix=time.time(), cls=cls, title=title)
                    self._store.append_event(self._sid, "windows", ev)
                    self._last_key = key
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
            except Exception as e:  # noqa: BLE001
                log.debug("hyprctl poll error: %s", e)
            self._stop.wait(self._interval)
