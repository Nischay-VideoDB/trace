from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from trace_cli.capture import service_mac


class FakeChannel:
    def __init__(self, channel_id: str) -> None:
        self.id = channel_id
        self.name = channel_id
        self.store = False
        self.is_primary = False


class FakeCaptureClient:
    instances: list["FakeCaptureClient"] = []

    def __init__(self, client_token: str) -> None:
        self.client_token = client_token
        self.started: tuple[str, list[FakeChannel]] | None = None
        self.stopped = False
        self.closed = False
        self.__class__.instances.append(self)

    async def request_permission(self, kind: str) -> bool:
        return True

    async def list_channels(self):
        return SimpleNamespace(
            displays=SimpleNamespace(default=FakeChannel("display:1")),
            mics=SimpleNamespace(default=FakeChannel("mic:default")),
        )

    async def start_session(self, capture_session_id: str, channels: list[FakeChannel]) -> None:
        self.started = (capture_session_id, channels)

    async def stop_session(self) -> None:
        self.stopped = True

    async def events(self):
        yield {"event": "recording-complete", "payload": {}}

    async def shutdown(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_sdk_start_uses_current_official_capture_contract(monkeypatch) -> None:
    import videodb
    import videodb.capture

    connection = SimpleNamespace(
        generate_client_token=lambda expires_in: f"short-token-{expires_in}",
        create_capture_session=lambda **kwargs: SimpleNamespace(id="cap-test"),
    )
    monkeypatch.setattr(videodb, "connect", lambda: connection)
    monkeypatch.setattr(videodb.capture, "CaptureClient", FakeCaptureClient)
    FakeCaptureClient.instances.clear()

    state: dict = {}
    ready = threading.Event()
    task = asyncio.create_task(service_mac._sdk_start(state, ready, [], True))
    for _ in range(100):
        if ready.is_set():
            break
        await asyncio.sleep(0.01)

    assert ready.is_set()
    client = FakeCaptureClient.instances[-1]
    assert client.client_token == "short-token-600"
    assert client.started is not None
    _, channels = client.started
    display = next(channel for channel in channels if channel.id == "display:1")
    assert display.store is True
    assert display.is_primary is True

    state["stop_event"].set()
    await task
    assert client.stopped is True
    assert client.closed is True


def test_export_poll_returns_permanent_video_id(monkeypatch) -> None:
    results = iter([
        {"export_status": "exporting"},
        {"export_status": "exported", "video_id": "m-z-trace-test"},
    ])
    session = SimpleNamespace(export=lambda: next(results), exported_video_id=None)
    connection = SimpleNamespace(get_capture_session=lambda _session_id: session)
    monkeypatch.setattr(service_mac.time, "sleep", lambda _seconds: None)

    assert service_mac._wait_for_exported_video(connection, "cap-test", timeout=1) == "m-z-trace-test"
