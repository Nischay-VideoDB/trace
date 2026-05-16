"""SessionManager: orchestrates start/stop lifecycle.

For v1 we keep capture in-process (foreground): `trace start` blocks until the
user hits Ctrl-C or runs `trace stop` from another shell which sends SIGINT
to this process via active.json/pid.

A simpler v1: `trace start` forks a daemon and writes pid; `trace stop` reads pid
and SIGINTs it. We implement the daemon-fork variant so the user can run
multiple shells without losing the recording.
"""
from __future__ import annotations

import errno
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from trace_cli.session.ids import new_session_id
from trace_cli.session.models import SessionMetadata
from trace_cli.session.store import ROOT, SessionStore

log = logging.getLogger("trace.manager")


class SessionError(Exception):
    pass


class ActiveSessionError(SessionError):
    pass


class NoActiveSession(SessionError):
    pass


class SessionManager:
    def __init__(self, store: SessionStore | None = None) -> None:
        self.store = store or SessionStore()

    # ----- start --------------------------------------------------------

    def create(self, *, project_dir: Path) -> SessionMetadata:
        """R1.4 + R1.8 checks, then write metadata. Caller spawns capture."""
        # R1.4
        active = self.store.find_active()
        if active is not None:
            raise ActiveSessionError(
                f"session {active.session_id} already active "
                f"(started {active.started_at.isoformat()})"
            )
        # R1.8
        self.store.ensure_writable()

        sid = new_session_id()
        meta = SessionMetadata(
            session_id=sid,
            started_at=datetime.now(timezone.utc),
            status="recording",
            capture_mode="local_ffmpeg",
            mic_status="enabled",
            project_dir=str(project_dir.resolve()),
        )
        self.store.write_metadata(meta)
        return meta

    def mark_active(self, session_id: str, pid: int) -> None:
        self.store.set_active(session_id, pid)

    # ----- stop ---------------------------------------------------------

    def signal_stop(self) -> SessionMetadata:
        """Read active.json, SIGINT the running pid. Returns the metadata."""
        meta = self.store.find_active()
        if meta is None:
            raise NoActiveSession("no active session")
        # Read pid from active.json directly (find_active discards it)
        from trace_cli.session.store import ACTIVE_FILE
        import json as _json
        try:
            data = _json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
            pid = int(data["pid"])
        except (OSError, _json.JSONDecodeError, KeyError, ValueError) as e:
            raise SessionError(f"active.json malformed: {e}") from e

        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            log.warning("active pid %d not running; clearing active state", pid)
            self.store.clear_active()
            raise NoActiveSession(f"recorded pid {pid} no longer exists") from None
        except OSError as e:
            if e.errno == errno.ESRCH:
                self.store.clear_active()
                raise NoActiveSession(f"pid {pid} gone") from e
            raise SessionError(f"failed to signal {pid}: {e}") from e
        return meta

    def wait_for_stop(self, session_id: str, timeout: float = 60.0) -> SessionMetadata:
        """Wait for the active worker to write status != recording."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                meta = self.store.read_metadata(session_id)
            except Exception:
                meta = None
            if meta and meta.status != "recording":
                return meta
            time.sleep(0.5)
        raise SessionError(f"worker did not finalize within {timeout}s")
