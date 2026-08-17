from __future__ import annotations

import logging

from trace_cli.credentials import Credentials, RedactingFormatter


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


def test_redacting_formatter_redacts_both_videodb_names_and_github(monkeypatch) -> None:
    secrets = {
        "VIDEO_DB_API_KEY": "canonical-videodb-secret",
        "VIDEODB_API_KEY": "legacy-videodb-secret",
        "GITHUB_TOKEN": "github-secret-token",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "trace", logging.INFO, __file__, 0,
        "keys: %s / %s / %s", tuple(secrets.values()), None,
    )
    rendered = formatter.format(record)

    for secret in secrets.values():
        assert secret not in rendered
        assert Credentials.redact(secret) in rendered
