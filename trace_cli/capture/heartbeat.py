"""Heartbeat writer thread. R1.7: <= 5s interval, elapsed + byte counts."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from trace_cli.session.models import Heartbeat
from trace_cli.session.store import SessionStore

log = logging.getLogger("trace.heartbeat")


class HeartbeatThread(threading.Thread):
    def __init__(
        self,
        session_id: str,
        store: SessionStore,
        screen_path: Path,
        audio_path: Path | None,
        interval: float = 4.0,
    ) -> None:
        super().__init__(name=f"heartbeat-{session_id[:8]}", daemon=True)
        self._sid = session_id
        self._store = store
        self._screen = screen_path
        self._audio = audio_path
        self._interval = interval
        self._stop = threading.Event()
        self._started_at = time.time()

    def stop(self) -> None:
        self._stop.set()

    def _size(self, p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                hb = Heartbeat(
                    elapsed_seconds=time.time() - self._started_at,
                    screen_bytes=self._size(self._screen),
                    audio_bytes=self._size(self._audio) if self._audio else 0,
                    timestamp=datetime.now(timezone.utc),
                )
                self._store.append_event(self._sid, "heartbeat", hb)
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat write failed: %s", e)
            self._stop.wait(self._interval)
