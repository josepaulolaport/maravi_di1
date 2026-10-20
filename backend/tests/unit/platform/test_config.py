"""Platform settings: our validators, the secret masking and the `.env` files we read. One
`Settings` class for every process, the broker URL required only where it is used.

Plan §3 (Wave 0: config), plan §1 (`platform/config.py`), backend/CLAUDE.md "Logging" (no
secrets) and "Commands" (`DATABASE_URL` in the SQLAlchemy ``postgresql+psycopg`` form). Defaults,
bounds, required fields and reading the environment are pydantic-settings' own behaviour,
declared on the fields, and are not retested here.
"""

from __future__ import annotations

import re
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
    monkeypatch.setenv("DATABASE_URL", URL)


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
    "url", ["http://di1:s3cret-pw@broker/", "di1:s3cret-pw@broker:5672", "s3cret-pw"]
)
def test_only_amqp_urls_are_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("RABBITMQ_URL", url)

    with pytest.raises(ValidationError, match="amqp://") as raised:
        Settings()

    assert "s3cret-pw" not in str(raised.value)


def test_the_broker_url_is_optional_until_it_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API never publishes, so it starts without ``RABBITMQ_URL``; the outbox relay and the
    worker read it through `Settings.broker_url`, which fails when it is missing."""
    assert Settings().rabbitmq_url is None
    with pytest.raises(MissingSettingError, match="RABBITMQ_URL is not set"):
        Settings().broker_url()

    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    assert Settings().broker_url().get_secret_value() == BROKER_URL


def test_no_password_appears_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RABBITMQ_URL", BROKER_URL)

    settings = Settings()

    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings)


@pytest.mark.parametrize(("value", "level"), [("info", "INFO"), ("Warning", "WARNING")])
def test_the_log_level_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch, value: str, level: str
) -> None:
    """uvicorn's ``--log-level`` and most tools write it in lower case."""
    monkeypatch.setenv("LOG_LEVEL", value)

    assert Settings().log_level == level


@pytest.fixture
def env_files_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Turn the `.env` files back on (tests/conftest.py turns them off) in a fake checkout:
    the working directory is ``<tmp>/backend``, as for every ``uv run`` in the Makefile."""
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setitem(Settings.model_config, "env_file", ENV_FILES)
    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.chdir(backend)
    return tmp_path


def test_settings_read_the_root_env_file_and_ignore_the_compose_variables(
    env_files_enabled: Path,
) -> None:
    """The repository root's `.env` is the one Compose reads too: its ``DI1_*`` lines are not
    settings and must not fail validation."""
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


ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"
"""The repository root's `.env.example`, which documents every backend setting with its
default ("every value below is the default")."""

EXAMPLES_NOT_DEFAULTS = {"DATABASE_URL", "RABBITMQ_URL", "HEARTBEAT_FILE"}
"""Lines that show the form of a value, not a default: the URLs are required or optional with no
default, and no heartbeat file is written unless one is set."""

DOCUMENTED = {
    "WORKER_SWEEP_INTERVAL_SECONDS",
    "OUTBOX_RETENTION_DAYS",
    "OUTBOX_RETENTION_INTERVAL_SECONDS",
    "HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_MAX_AGE_SECONDS",
    "RABBITMQ_PUBLISH_TIMEOUT_SECONDS",
    "OUTBOX_RELAY_BATCH_SIZE",
}
"""Defaults the README and compose.yaml also quote (the 5 s sweep, the 7-day retention, ...)."""


def _documented_defaults() -> dict[str, str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    pairs = (re.fullmatch(r"# ([A-Z_]+)=(\S+)", line) for line in lines)
    return {m[1]: m[2] for m in pairs if m and m[1] not in EXAMPLES_NOT_DEFAULTS}


def test_the_defaults_are_the_documented_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    """The expected values come from `.env.example`, not from the code: the settings built from
    the documented values must equal the defaults, so a default changed in one place and not the
    other fails here."""
    documented = _documented_defaults()
    assert documented.keys() >= DOCUMENTED
    defaults = Settings()

    for name, value in documented.items():
        monkeypatch.setenv(name, value)

    assert Settings() == defaults
