"""Shared fixtures for every backend test."""

from __future__ import annotations

import pytest

from di1.platform.config import BrokerSettings, HeartbeatSettings, LoggingSettings, Settings


@pytest.fixture(autouse=True)
def no_env_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read only the process environment in tests: a developer's `.env` (README
    "Configuration") must not change what a test sees."""
    for cls in (Settings, BrokerSettings, HeartbeatSettings, LoggingSettings):
        monkeypatch.setitem(cls.model_config, "env_file", None)
