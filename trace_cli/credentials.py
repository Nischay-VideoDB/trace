"""Env-var credential loading + redaction (R11)."""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from dotenv import load_dotenv

# Load .env once at import time (repo root). Idempotent.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

REQUIRED_ENV = (
    "VIDEODB_API_KEY",
    "GITHUB_TOKEN",
)


class Credentials:
    """Static helpers for env-var validation and key redaction (R11)."""

    REQUIRED_ENV = REQUIRED_ENV

    @staticmethod
    def is_missing(value: str | None) -> bool:
        # R11.1: None, empty, whitespace-only all count as missing
        return value is None or value.strip() == ""

    @staticmethod
    def collect_missing(required: Iterable[str]) -> list[str]:
        return [name for name in required if Credentials.is_missing(os.environ.get(name))]

    @staticmethod
    def redact(value: str) -> str:
        # R11.3: <8 chars → "********"; else len-4 stars + last 4
        if len(value) < 8:
            return "*" * 8
        return ("*" * (len(value) - 4)) + value[-4:]

    @classmethod
    def require(cls, *names: str) -> None:
        """Exit 2 with stderr message listing missing vars (R11.2)."""
        missing = cls.collect_missing(names)
        if missing:
            sys.stderr.write(
                f"Missing required environment variables: {', '.join(missing)}\n"
            )
            sys.stderr.write(
                "Set them in /home/cryptosaiyan/Documents/trace/.env or your shell.\n"
            )
            sys.exit(2)


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts known API key values from messages."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        super().__init__(fmt, datefmt)
        self._secrets: list[str] = []
        for name in REQUIRED_ENV:
            v = os.environ.get(name)
            if v and not Credentials.is_missing(v):
                self._secrets.append(v)

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for secret in self._secrets:
            if secret in msg:
                msg = msg.replace(secret, Credentials.redact(secret))
        return msg


def install_redacting_logging(level: int = logging.INFO) -> None:
    """Replace root logger handlers with a redacting one."""
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
