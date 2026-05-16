"""Session_Store: ~/.trace/sessions/{session_id}/ on disk layout (R10)."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from trace_cli.session.ids import is_valid_session_id
from trace_cli.session.models import SessionMetadata

log = logging.getLogger("trace.store")

ROOT = Path(os.environ.get("TRACE_HOME", str(Path.home() / ".trace")))
SESSIONS_DIR = ROOT / "sessions"
ACTIVE_FILE = ROOT / "active.json"
PR_LINKS_FILE = ROOT / "pr_links.json"


class StoreError(Exception):
    pass


def _ensure_dir(path: Path) -> None:
    """Create dirs with 0o700 perms. Retry once after 200ms on failure (R10.7)."""
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return
    except OSError as e:
        log.warning("mkdir %s failed (%s); retrying in 0.2s", path, e)
        time.sleep(0.2)
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as e2:
            raise StoreError(f"cannot create {path}: {e2}") from e2


def _atomic_write_text(path: Path, content: str) -> None:
    """Write tmp then rename for crash-safety."""
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


class SessionStore:
    """Owns the on-disk layout (R10)."""

    def __init__(self, root: Path = SESSIONS_DIR) -> None:
        self.root = root
        _ensure_dir(self.root)

    # ---- paths ----------------------------------------------------------

    def session_dir(self, session_id: str) -> Path:
        if not is_valid_session_id(session_id):
            raise StoreError(f"invalid session_id {session_id!r}")
        return self.root / session_id

    def metadata_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "metadata.json"

    def screen_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "screen.mp4"

    def audio_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "audio.wav"

    def transcript_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "transcript.json"

    def timeline_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "timeline.json"

    def events_path(self, session_id: str, name: str) -> Path:
        return self.session_dir(session_id) / f"events_{name}.jsonl"

    def artifact_path(self, session_id: str, name: str) -> Path:
        return self.session_dir(session_id) / name

    # ---- writability check (R1.8) --------------------------------------

    def ensure_writable(self) -> None:
        _ensure_dir(self.root)
        if not os.access(self.root, os.W_OK):
            raise StoreError(f"Session_Store {self.root} not writable")

    # ---- metadata -------------------------------------------------------

    def write_metadata(self, meta: SessionMetadata) -> None:
        sd = self.session_dir(meta.session_id)
        _ensure_dir(sd)
        _atomic_write_text(self.metadata_path(meta.session_id), meta.model_dump_json(indent=2))

    def read_metadata(self, session_id: str) -> SessionMetadata:
        try:
            raw = self.metadata_path(session_id).read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise StoreError(f"session not found: {session_id}") from e
        return SessionMetadata.model_validate_json(raw)

    def update_metadata(self, session_id: str, **fields: Any) -> SessionMetadata:
        """Preserve all previously written fields (R10.3)."""
        cur = self.read_metadata(session_id)
        new = cur.model_copy(update=fields)
        self.write_metadata(new)
        return new

    def list_sessions(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and is_valid_session_id(p.name))

    def find_active(self) -> SessionMetadata | None:
        """Returns the metadata of an active session, if any (R1.4)."""
        if not ACTIVE_FILE.exists():
            return None
        try:
            data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        sid = data.get("session_id")
        if not sid:
            return None
        try:
            meta = self.read_metadata(sid)
        except StoreError:
            return None
        if meta.status in ("active", "recording"):
            return meta
        return None

    def set_active(self, session_id: str, pid: int) -> None:
        _ensure_dir(ROOT)
        _atomic_write_text(
            ACTIVE_FILE,
            json.dumps(
                {"session_id": session_id, "pid": pid, "started_at": datetime.now(timezone.utc).isoformat()},
                indent=2,
            ),
        )

    def clear_active(self) -> None:
        try:
            ACTIVE_FILE.unlink()
        except FileNotFoundError:
            pass

    # ---- jsonl event appends (heartbeat, saves, windows) ---------------

    def append_event(self, session_id: str, name: str, event: BaseModel | dict[str, Any]) -> None:
        path = self.events_path(session_id, name)
        _ensure_dir(path.parent)
        data = event.model_dump(mode="json") if isinstance(event, BaseModel) else event
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read_events(self, session_id: str, name: str) -> list[dict[str, Any]]:
        path = self.events_path(session_id, name)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("malformed event line in %s: %r", path, line[:80])
        return out

    # ---- PR link mapping -----------------------------------------------

    def link_pr(self, pr_url: str, session_id: str) -> None:
        _ensure_dir(ROOT)
        links: dict[str, str] = {}
        if PR_LINKS_FILE.exists():
            try:
                links = json.loads(PR_LINKS_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                links = {}
        links[pr_url] = session_id
        _atomic_write_text(PR_LINKS_FILE, json.dumps(links, indent=2))

    def session_for_pr(self, pr_url: str) -> str | None:
        if not PR_LINKS_FILE.exists():
            return None
        try:
            return json.loads(PR_LINKS_FILE.read_text(encoding="utf-8")).get(pr_url)
        except json.JSONDecodeError:
            return None
