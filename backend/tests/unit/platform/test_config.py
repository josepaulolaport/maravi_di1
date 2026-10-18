"""Platform settings come from the environment, validated, with secrets never shown.

Plan §3 (Wave 0: config), plan §1 (`platform/config.py`), backend/CLAUDE.md "Logging" (no
secrets) and "Commands" (`DATABASE_URL` in the SQLAlchemy ``postgresql+psycopg`` form).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from di1.platform.config import Settings, get_settings

URL = "postgresql+psycopg://di1:s3cret-pw@db:5432/di1"
ENV_NAMES = ("DATABASE_URL", "DATABASE_POOL_SIZE", "DATABASE_MAX_OVERFLOW", "DATABASE_ECHO")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_reads_the_database_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert settings.database_url.get_secret_value() == URL


def test_pool_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert (settings.database_pool_size, settings.database_max_overflow) == (5, 10)
    assert settings.database_echo is False


def test_pool_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("DATABASE_POOL_SIZE", "3")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DATABASE_ECHO", "true")

    settings = Settings()

    assert (settings.database_pool_size, settings.database_max_overflow) == (3, 0)
    assert settings.database_echo is True


def test_the_database_url_is_required() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://di1:s3cret-pw@db:5432/di1",
        "postgresql+asyncpg://di1:s3cret-pw@db:5432/di1",
        "sqlite+aiosqlite:///s3cret-pw.db",
        "not a url s3cret-pw",
    ],
)
def test_only_the_async_psycopg_driver_is_accepted(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValidationError, match="postgresql\\+psycopg") as raised:
        Settings()

    assert "s3cret-pw" not in str(raised.value)


@pytest.mark.parametrize(
    ("name", "value"), [("DATABASE_POOL_SIZE", "0"), ("DATABASE_MAX_OVERFLOW", "-1")]
)
def test_pool_bounds(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


def test_the_password_never_appears_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings)


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.database_echo = True  # type: ignore[misc]


def test_get_settings_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    first = get_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://other:pw@db:5432/other")

    second = get_settings()

    assert first.database_url != second.database_url
