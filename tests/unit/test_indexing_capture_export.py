from __future__ import annotations

from datetime import datetime, timezone

from trace_cli.indexing import pipeline
from trace_cli.session.models import SessionMetadata
from trace_cli.session.store import SessionStore


class FakeVideo:
    id = "m-z-provider-export"
    length = 4.0

    def get_transcript(self, **_kwargs):
        return [{"start": 0, "end": 2, "text": "The capture export is reusable."}]


class FakeClient:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.upload_calls = 0

    def get_video(self, video_id: str):
        self.get_calls.append(video_id)
        return FakeVideo()

    def upload_file(self, *_args, **_kwargs):
        self.upload_calls += 1
        raise AssertionError("Capture SDK exports must not be uploaded twice")

    def index_video_spoken(self, _video) -> None:
        return None

    def index_video_scenes(self, _video, *, prompt: str, time_seconds: int) -> str:
        assert "code_editor" in prompt
        assert time_seconds == 10
        return "scene-index-test"

    def stop_sandbox(self) -> None:
        return None


def test_indexing_reuses_capture_sdk_export_without_local_mp4(tmp_path, monkeypatch) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    session_id = "trace-test-session"
    store.write_metadata(SessionMetadata(
        session_id=session_id,
        started_at=datetime.now(timezone.utc),
        status="processing",
        capture_mode="rtstream",
        mic_status="enabled",
        video_id="m-z-provider-export",
    ))
    client = FakeClient()
    monkeypatch.setattr(pipeline, "VideoDBClient", lambda: client)

    result = pipeline.run_indexing(session_id, store=store)

    assert result.status == "indexed"
    assert result.video_id == "m-z-provider-export"
    assert result.model_extra["scene_index_id"] == "scene-index-test"
    assert client.get_calls == ["m-z-provider-export"]
    assert client.upload_calls == 0
    assert "reusable" in store.transcript_path(session_id).read_text()
