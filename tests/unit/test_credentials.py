from __future__ import annotations

from trace_cli.credentials import Credentials


def test_released_videodb_env_name_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("VIDEO_DB_API_KEY", "released-key")
    monkeypatch.delenv("VIDEODB_API_KEY", raising=False)

    assert Credentials.collect_missing(["VIDEO_DB_API_KEY"]) == []
    assert Credentials.videodb_api_key() == "released-key"


def test_legacy_videodb_env_name_remains_a_read_only_alias(monkeypatch) -> None:
    monkeypatch.delenv("VIDEO_DB_API_KEY", raising=False)
    monkeypatch.setenv("VIDEODB_API_KEY", "legacy-key")

    assert Credentials.collect_missing(["VIDEO_DB_API_KEY"]) == []
    assert Credentials.videodb_api_key() == "legacy-key"
