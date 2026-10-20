"""``python -m di1.workers.healthcheck``: compose.yaml's health check of ``worker`` and
``outbox-relay``. Healthy while the process's heartbeat file is fresh."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from di1.workers.healthcheck import check


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker containers' environment: the process settings, which the check reads too."""
    for name in ("HEARTBEAT_FILE", "HEARTBEAT_MAX_AGE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://di1:s3cret-pw@db:5432/di1")


def test_a_fresh_heartbeat_is_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "worker.heartbeat"
    path.touch()
    monkeypatch.setenv("HEARTBEAT_FILE", str(path))

    assert check() == 0


def test_a_stale_heartbeat_is_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "worker.heartbeat"
    path.touch()
    old = time.time() - 61
    os.utime(path, (old, old))
    monkeypatch.setenv("HEARTBEAT_FILE", str(path))
    monkeypatch.setenv("HEARTBEAT_MAX_AGE_SECONDS", "60")

    assert check() == 1
    assert "older than 60" in capsys.readouterr().err


def test_a_missing_heartbeat_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEARTBEAT_FILE", str(tmp_path / "never-written"))

    assert check() == 1


def test_no_heartbeat_file_configured_is_unhealthy(capsys: pytest.CaptureFixture[str]) -> None:
    assert check() == 1
    assert "HEARTBEAT_FILE" in capsys.readouterr().err


def test_invalid_settings_are_unhealthy_without_their_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://di1:s3cret-pw@db:5432/di1")

    assert check() == 1
    err = capsys.readouterr().err
    assert "invalid settings" in err
    assert "database_url" in err
    assert "s3cret-pw" not in err
