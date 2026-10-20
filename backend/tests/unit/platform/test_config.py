"""Platform settings come from the environment, validated, with secrets never shown: one
`Settings` class for every process, the broker URL required only where it is used.

Plan §3 (Wave 0: config), plan §1 (`platform/config.py`), backend/CLAUDE.md "Logging" (no
secrets) and "Commands" (`DATABASE_URL` in the SQLAlchemy ``postgresql+psycopg`` form).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from di1.platform.config import ENV_FILES, MissingSettingError, Settings

URL = "postgresql+psycopg://di1:s3cret-pw@db:5432/di1"
BROKER_URL = "amqp://di1:s3cret-pw@broker:5672/"
ENV_NAMES = tuple(name.upper() for name in Settings.model_fields)


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


def test_worker_timeout_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Long enough for one date's transaction, short enough that a hung query or lock wait
    ends the worker's unit of work instead of hanging it."""
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert settings.worker_statement_timeout_seconds == 60
    assert settings.worker_lock_timeout_seconds == 10


def test_worker_timeouts_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("WORKER_STATEMENT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("WORKER_LOCK_TIMEOUT_SECONDS", "2.5")

    settings = Settings()

    assert settings.worker_statement_timeout_seconds == 120
    assert settings.worker_lock_timeout_seconds == 2.5


@pytest.mark.parametrize(
    "name", ["WORKER_STATEMENT_TIMEOUT_SECONDS", "WORKER_LOCK_TIMEOUT_SECONDS"]
)
def test_worker_timeouts_are_positive(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


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


def test_settings_are_read_when_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    first = Settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://other:pw@db:5432/other")

    second = Settings()

    assert first.database_url != second.database_url


def test_the_broker_url_is_optional_until_it_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API never publishes, so it starts without ``RABBITMQ_URL``; the outbox relay and the
    worker read it through `Settings.broker_url`, which fails when it is missing."""
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert settings.rabbitmq_url is None
    with pytest.raises(MissingSettingError, match="RABBITMQ_URL is not set"):
        settings.broker_url()


def test_broker_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    settings = Settings()

    assert settings.broker_url().get_secret_value() == BROKER_URL
    assert settings.rabbitmq_publish_timeout_seconds == 10.0
    assert settings.outbox_relay_batch_size == 100
    assert settings.outbox_relay_poll_interval_seconds == 1.0
    assert settings.outbox_relay_retry_base_delay_seconds == 1.0
    assert settings.outbox_relay_retry_max_delay_seconds == 60.0
    assert settings.outbox_retention_days == 7
    assert settings.outbox_retention_interval_seconds == 3600.0
    assert settings.worker_sweep_interval_seconds == 5.0


def test_broker_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("RABBITMQ_URL", "amqps://di1:s3cret-pw@broker:5671/di1")
    monkeypatch.setenv("RABBITMQ_PUBLISH_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("OUTBOX_RELAY_BATCH_SIZE", "10")
    monkeypatch.setenv("OUTBOX_RELAY_POLL_INTERVAL_SECONDS", "0.2")
    monkeypatch.setenv("OUTBOX_RELAY_RETRY_BASE_DELAY_SECONDS", "2")
    monkeypatch.setenv("OUTBOX_RELAY_RETRY_MAX_DELAY_SECONDS", "8")
    monkeypatch.setenv("OUTBOX_RETENTION_DAYS", "14")
    monkeypatch.setenv("OUTBOX_RETENTION_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("WORKER_SWEEP_INTERVAL_SECONDS", "0.5")

    settings = Settings()

    assert settings.rabbitmq_publish_timeout_seconds == 2.5
    assert settings.outbox_relay_batch_size == 10
    assert settings.outbox_relay_poll_interval_seconds == 0.2
    assert settings.outbox_relay_retry_base_delay_seconds == 2.0
    assert settings.outbox_relay_retry_max_delay_seconds == 8.0
    assert settings.outbox_retention_days == 14
    assert settings.outbox_retention_interval_seconds == 900.0
    assert settings.worker_sweep_interval_seconds == 0.5


@pytest.mark.parametrize(
    "url", ["http://di1:s3cret-pw@broker/", "di1:s3cret-pw@broker:5672", "s3cret-pw"]
)
def test_only_amqp_urls_are_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("RABBITMQ_URL", url)

    with pytest.raises(ValidationError, match="amqp://") as raised:
        Settings()

    assert "s3cret-pw" not in str(raised.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RABBITMQ_PUBLISH_TIMEOUT_SECONDS", "0"),
        ("OUTBOX_RELAY_BATCH_SIZE", "0"),
        ("OUTBOX_RELAY_POLL_INTERVAL_SECONDS", "0"),
        ("OUTBOX_RELAY_RETRY_BASE_DELAY_SECONDS", "0"),
        ("OUTBOX_RELAY_RETRY_MAX_DELAY_SECONDS", "0"),
        ("OUTBOX_RETENTION_DAYS", "0"),
        ("OUTBOX_RETENTION_INTERVAL_SECONDS", "0"),
        ("WORKER_SWEEP_INTERVAL_SECONDS", "0"),
        ("HEARTBEAT_INTERVAL_SECONDS", "0"),
        ("HEARTBEAT_MAX_AGE_SECONDS", "0"),
    ],
)
def test_broker_and_heartbeat_bounds(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


def test_no_password_appears_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    settings = Settings()

    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings)


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_the_log_level_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOG_LEVEL", level)

    assert Settings().log_level == level


def test_the_log_level_defaults_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    assert Settings().log_level == "INFO"


def test_an_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError, match="log_level"):
        Settings()


@pytest.mark.parametrize(("value", "level"), [("info", "INFO"), ("Warning", "WARNING")])
def test_the_log_level_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch, value: str, level: str
) -> None:
    """uvicorn's ``--log-level`` and most tools write it in lower case."""
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOG_LEVEL", value)

    assert Settings().log_level == level


def test_heartbeat_settings_default_to_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    settings = Settings()

    assert settings.heartbeat_file is None
    assert (settings.heartbeat_interval_seconds, settings.heartbeat_max_age_seconds) == (5.0, 30.0)


def test_heartbeat_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("HEARTBEAT_FILE", "/tmp/di1-worker.heartbeat")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "2")
    monkeypatch.setenv("HEARTBEAT_MAX_AGE_SECONDS", "60")

    settings = Settings()

    assert settings.heartbeat_file == Path("/tmp/di1-worker.heartbeat")
    assert (settings.heartbeat_interval_seconds, settings.heartbeat_max_age_seconds) == (2.0, 60.0)


@pytest.fixture
def env_files_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Turn the `.env` files back on (tests/conftest.py turns them off) in a fake checkout:
    the working directory is ``<tmp>/backend``, as for every ``uv run`` in the Makefile."""
    monkeypatch.setitem(Settings.model_config, "env_file", ENV_FILES)
    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.chdir(backend)
    return tmp_path


def test_the_settings_read_the_root_then_the_backend_env_file() -> None:
    """The repository root's `.env` (shared with Compose), then ``backend/.env``, relative to
    the working directory ``backend/``."""
    assert ENV_FILES == ("../.env", ".env")
    assert Settings.model_config.get("env_file_encoding") == "utf-8"


def test_tests_never_read_a_developers_env_file() -> None:
    assert Settings.model_config.get("env_file") is None


def test_settings_read_the_root_env_file(
    env_files_enabled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (env_files_enabled / ".env").write_text(
        f"DATABASE_URL={URL}\nRABBITMQ_URL={BROKER_URL}\nLOG_LEVEL=debug\n"
        "HEARTBEAT_FILE=/tmp/hb\nDI1_DB_USER=ignored\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.database_url.get_secret_value() == URL
    assert settings.broker_url().get_secret_value() == BROKER_URL
    assert settings.log_level == "DEBUG"
    assert settings.heartbeat_file == Path("/tmp/hb")


def test_backend_env_file_overrides_the_root_one(env_files_enabled: Path) -> None:
    (env_files_enabled / ".env").write_text(f"DATABASE_URL={URL}\n", encoding="utf-8")
    other = "postgresql+psycopg://local:pw@127.0.0.1:5432/local"
    (env_files_enabled / "backend" / ".env").write_text(f"DATABASE_URL={other}\n", encoding="utf-8")

    assert Settings().database_url.get_secret_value() == other


def test_the_process_environment_overrides_the_env_files(
    env_files_enabled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (env_files_enabled / ".env").write_text(
        f"DATABASE_URL={URL}\nDATABASE_POOL_SIZE=3\n", encoding="utf-8"
    )
    other = "postgresql+psycopg://other:pw@db:5432/other"
    monkeypatch.setenv("DATABASE_URL", other)

    settings = Settings()

    assert settings.database_url.get_secret_value() == other
    assert settings.database_pool_size == 3


def test_missing_env_files_are_ignored(
    env_files_enabled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)

    assert Settings().database_url.get_secret_value() == URL
