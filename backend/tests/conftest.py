"""Shared fixtures for every backend test."""

from __future__ import annotations

import pytest

from di1.platform.config import Settings
from tests.support.db import drop_template


@pytest.fixture(autouse=True)
def no_env_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read only the process environment in tests: a developer's `.env`
    (docs/development.md, "Configuration") must not change what a test sees."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """The migrated template outlives every test's database; it goes with the session."""
    drop_template()
