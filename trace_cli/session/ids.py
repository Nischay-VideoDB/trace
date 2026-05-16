"""Session id generation + validation (R1.1, R10.1)."""
from __future__ import annotations

import re
import uuid

_ID_RE = re.compile(r"^[a-z0-9-]{8,64}$")


def new_session_id() -> str:
    """UUID v4, lowercase, hyphenated (36 chars)."""
    return str(uuid.uuid4())


def is_valid_session_id(s: str) -> bool:
    return bool(_ID_RE.match(s))
