"""Platform settings come from the environment, validated, with secrets never shown.

Plan §3 (Wave 0: config), plan §1 (`platform/config.py`), backend/CLAUDE.md "Logging" (no
secrets) and "Commands" (`DATABASE_URL` in the SQLAlchemy ``postgresql+psycopg`` form).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from di1.platform.config import (
    BrokerSettings,
    LoggingSettings,
    Settings,
    get_broker_settings,
    get_heartbeat_settings,
    get_logging_settings,
    get_settings,
)

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


BROKER_URL = "amqp://di1:s3cret-pw@broker:5672/"
BROKER_ENV_NAMES = (
    "RABBITMQ_URL",
    "RABBITMQ_PREFETCH_COUNT",
    "RABBITMQ_DELIVERY_LIMIT",
    "RABBITMQ_RETRY_BASE_DELAY_SECONDS",
    "RABBITMQ_RETRY_MAX_DELAY_SECONDS",
    "RABBITMQ_PUBLISH_TIMEOUT_SECONDS",
    "OUTBOX_RELAY_BATCH_SIZE",
    "OUTBOX_RELAY_POLL_INTERVAL_SECONDS",
    "OUTBOX_RELAY_RETRY_BASE_DELAY_SECONDS",
    "OUTBOX_RELAY_RETRY_MAX_DELAY_SECONDS",
    "INBOX_RETENTION_DAYS",
    "INBOX_RETENTION_INTERVAL_SECONDS",
)


@pytest.fixture
def clean_broker_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in BROKER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("clean_broker_environment")
def test_broker_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    settings = BrokerSettings()

    assert settings.rabbitmq_url.get_secret_value() == BROKER_URL
    assert (settings.rabbitmq_prefetch_count, settings.rabbitmq_delivery_limit) == (1, 5)
    assert settings.rabbitmq_retry_base_delay_seconds == 1.0
    assert settings.rabbitmq_retry_max_delay_seconds == 30.0
    assert settings.rabbitmq_publish_timeout_seconds == 10.0
    assert settings.outbox_relay_batch_size == 100
    assert settings.outbox_relay_poll_interval_seconds == 1.0
    assert settings.outbox_relay_retry_base_delay_seconds == 1.0
    assert settings.outbox_relay_retry_max_delay_seconds == 60.0
    assert settings.inbox_retention_days == 7
    assert settings.inbox_retention_interval_seconds == 3600.0


@pytest.mark.usefixtures("clean_broker_environment")
def test_broker_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RABBITMQ_URL", "amqps://di1:s3cret-pw@broker:5671/di1")
    monkeypatch.setenv("RABBITMQ_PREFETCH_COUNT", "4")
    monkeypatch.setenv("RABBITMQ_DELIVERY_LIMIT", "2")
    monkeypatch.setenv("RABBITMQ_RETRY_BASE_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("RABBITMQ_RETRY_MAX_DELAY_SECONDS", "4")
    monkeypatch.setenv("RABBITMQ_PUBLISH_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("OUTBOX_RELAY_BATCH_SIZE", "10")
    monkeypatch.setenv("OUTBOX_RELAY_POLL_INTERVAL_SECONDS", "0.2")
    monkeypatch.setenv("OUTBOX_RELAY_RETRY_BASE_DELAY_SECONDS", "2")
    monkeypatch.setenv("OUTBOX_RELAY_RETRY_MAX_DELAY_SECONDS", "8")
    monkeypatch.setenv("INBOX_RETENTION_DAYS", "30")
    monkeypatch.setenv("INBOX_RETENTION_INTERVAL_SECONDS", "600")

    settings = get_broker_settings()

    assert (settings.rabbitmq_prefetch_count, settings.rabbitmq_delivery_limit) == (4, 2)
    assert settings.rabbitmq_retry_base_delay_seconds == 0.5
    assert settings.rabbitmq_retry_max_delay_seconds == 4.0
    assert settings.rabbitmq_publish_timeout_seconds == 2.5
    assert settings.outbox_relay_batch_size == 10
    assert settings.outbox_relay_poll_interval_seconds == 0.2
    assert settings.outbox_relay_retry_base_delay_seconds == 2.0
    assert settings.outbox_relay_retry_max_delay_seconds == 8.0
    assert settings.inbox_retention_days == 30
    assert settings.inbox_retention_interval_seconds == 600.0


@pytest.mark.usefixtures("clean_broker_environment")
def test_the_broker_url_is_required_but_the_database_url_is_not() -> None:
    with pytest.raises(ValidationError, match="rabbitmq_url") as raised:
        BrokerSettings()

    assert "database_url" not in str(raised.value)


@pytest.mark.usefixtures("clean_broker_environment")
@pytest.mark.parametrize(
    "url", ["http://di1:s3cret-pw@broker/", "di1:s3cret-pw@broker:5672", "s3cret-pw"]
)
def test_only_amqp_urls_are_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("RABBITMQ_URL", url)

    with pytest.raises(ValidationError, match="amqp://") as raised:
        BrokerSettings()

    assert "s3cret-pw" not in str(raised.value)


@pytest.mark.usefixtures("clean_broker_environment")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RABBITMQ_PREFETCH_COUNT", "0"),
        ("RABBITMQ_DELIVERY_LIMIT", "0"),
        ("RABBITMQ_RETRY_BASE_DELAY_SECONDS", "0"),
        ("RABBITMQ_RETRY_MAX_DELAY_SECONDS", "0"),
        ("RABBITMQ_PUBLISH_TIMEOUT_SECONDS", "0"),
        ("OUTBOX_RELAY_BATCH_SIZE", "0"),
        ("OUTBOX_RELAY_POLL_INTERVAL_SECONDS", "0"),
        ("OUTBOX_RELAY_RETRY_BASE_DELAY_SECONDS", "0"),
        ("OUTBOX_RELAY_RETRY_MAX_DELAY_SECONDS", "0"),
        ("INBOX_RETENTION_DAYS", "0"),
        ("INBOX_RETENTION_INTERVAL_SECONDS", "0"),
    ],
)
def test_broker_bounds(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        BrokerSettings()


@pytest.mark.usefixtures("clean_broker_environment")
def test_the_broker_password_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    settings = BrokerSettings()

    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings)


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_the_log_level_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    monkeypatch.setenv("LOG_LEVEL", level)

    assert get_logging_settings().log_level == level


def test_the_log_level_defaults_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert LoggingSettings().log_level == "INFO"


def test_an_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError, match="log_level"):
        LoggingSettings()


@pytest.mark.parametrize(("value", "level"), [("info", "INFO"), ("Warning", "WARNING")])
def test_the_log_level_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch, value: str, level: str
) -> None:
    """uvicorn's ``--log-level`` and most tools write it in lower case."""
    monkeypatch.setenv("LOG_LEVEL", value)

    assert LoggingSettings().log_level == level


def test_heartbeat_settings_default_to_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HEARTBEAT_FILE", "HEARTBEAT_INTERVAL_SECONDS", "HEARTBEAT_MAX_AGE_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    settings = get_heartbeat_settings()

    assert settings.heartbeat_file is None
    assert (settings.heartbeat_interval_seconds, settings.heartbeat_max_age_seconds) == (5.0, 30.0)


def test_heartbeat_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEARTBEAT_FILE", "/tmp/di1-worker.heartbeat")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "2")
    monkeypatch.setenv("HEARTBEAT_MAX_AGE_SECONDS", "60")

    settings = get_heartbeat_settings()

    assert settings.heartbeat_file == Path("/tmp/di1-worker.heartbeat")
    assert (settings.heartbeat_interval_seconds, settings.heartbeat_max_age_seconds) == (2.0, 60.0)
