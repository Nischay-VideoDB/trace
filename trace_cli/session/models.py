"""Pydantic v2 models for sessions, transcripts, timelines."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# R10.1: 8-64 chars, lowercase alnum + hyphen
_ID_RE = re.compile(r"^[a-z0-9-]{8,64}$")

SessionStatus = Literal[
    "active",
    "recording",
    "processing",
    "indexed",
    "completed",
    "failed",
    "indexing_failed",
    "transcription_failed",
]
CaptureMode = Literal["rtstream", "local_ffmpeg", "fallback"]
MicStatus = Literal["enabled", "denied"]


class SessionMetadata(BaseModel):
    """R1.1, R10.2, R10.3."""
    model_config = ConfigDict(extra="allow")  # tolerate forward-compatible additions

    session_id: str
    started_at: datetime
    stopped_at: datetime | None = None
    status: SessionStatus = "active"
    capture_mode: CaptureMode
    mic_status: MicStatus
    pr_url: str | None = None
    rtstream_id: str | None = None
    rtstream_url: str | None = None
    video_id: str | None = None
    project_dir: str | None = None
    tunnel_url: str | None = None

    @field_validator("session_id")
    @classmethod
    def _vid(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"invalid session_id {v!r}: must match {_ID_RE.pattern}")
        return v


class Heartbeat(BaseModel):
    """R1.7: emitted every <= 5s during capture."""
    elapsed_seconds: float = Field(ge=0)
    screen_bytes: int = Field(ge=0)
    audio_bytes: int = Field(ge=0)
    timestamp: datetime


class TranscriptSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float
    text: str
    uncertainty: bool = False

    @model_validator(mode="after")
    def _ord(self) -> "TranscriptSegment":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must exceed start_seconds")
        return self


class Transcript(BaseModel):
    session_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)


TaggedCategory = Literal["stuck", "research", "progress", "speech"]


class TaggedMoment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float
    category: TaggedCategory
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""

    @model_validator(mode="after")
    def _ord(self) -> "TaggedMoment":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must exceed start_seconds")
        return self


class Timeline(BaseModel):
    session_id: str
    session_end_seconds: float = Field(ge=0)
    moments: list[TaggedMoment] = Field(default_factory=list)


class SaveEvent(BaseModel):
    """Editor file save event captured by inotify."""
    t_unix: float
    path: str
    kind: str = "close_write"


class WindowEvent(BaseModel):
    """Foreground window snapshot from hyprctl."""
    t_unix: float
    cls: str = ""
    title: str = ""
