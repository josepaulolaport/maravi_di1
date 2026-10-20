"""Process settings, read from the environment (plan §3, Wave 0).

One `Settings` class for every process: the API, the migrations, the outbox relay, the processing
worker and its health check. Every value comes from configuration (OQ-5): the process
environment, else the `.env` files in `ENV_FILES`, else the field's default. Environment names are
the field names in upper case (``DATABASE_URL``, ``RABBITMQ_URL``, ...); the settings are read when
a process starts (``Settings()``), never at import time.

Secrets (the two URLs, which carry passwords) are `SecretStr`, so ``repr``, ``str`` and logs show
``**********``, and validation errors never echo their input (``hide_input_in_errors``).

``DATABASE_URL`` is required everywhere. ``RABBITMQ_URL`` is optional, because the API never
publishes (a write only saves an outbox row): the processes that use the broker read it through
`Settings.broker_url`, which fails at their startup when it is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_DRIVER = "postgresql+psycopg"
BROKER_SCHEMES = ("amqp", "amqps")

ENV_FILES = ("../.env", ".env")
"""Read relative to the working directory, ``backend/`` for every ``uv run``: the repository
root's `.env` (the one Compose interpolates), then ``backend/.env``, which wins over it. A missing
file is skipped; in the image neither exists, and Compose sets the environment."""

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class MissingSettingError(RuntimeError):
    """A setting the process needs is not set (its message names the variable, never a value)."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
    )

    # --- PostgreSQL: every process --------------------------------------------------------------
    database_url: SecretStr
    """SQLAlchemy URL, ``postgresql+psycopg://user:password@host:port/database``."""
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_echo: bool = False
    worker_statement_timeout_seconds: float = Field(default=60.0, gt=0)
    """``statement_timeout`` of the processing worker's connections (`create_worker_engine`):
    longer than one date's transaction, so a hung query fails the unit of work instead of
    hanging the worker while its heartbeat keeps it healthy. The API keeps the server default."""
    worker_lock_timeout_seconds: float = Field(default=10.0, gt=0)
    """``lock_timeout`` of the processing worker's connections: the longest wait for a row or
    advisory lock (a cancel or a write holds one only for its own short transaction)."""

    # --- RabbitMQ: the outbox relay and the processing worker -----------------------------------
    rabbitmq_url: SecretStr | None = None
    """``amqp://user:password@host:port/vhost``; read through `broker_url`."""
    rabbitmq_publish_timeout_seconds: float = Field(default=10.0, gt=0)
    outbox_relay_batch_size: int = Field(default=100, ge=1)
    outbox_relay_poll_interval_seconds: float = Field(default=1.0, gt=0)
    outbox_relay_retry_base_delay_seconds: float = Field(default=1.0, gt=0)
    """Pause before the relay retries a row it failed to publish, doubled on each attempt, so a
    failing row is not retried on every poll."""
    outbox_relay_retry_max_delay_seconds: float = Field(default=60.0, gt=0)
    outbox_retention_days: int = Field(default=7, ge=1)
    """Outbox rows published longer ago than this are deleted by the outbox relay; an
    unpublished row is never deleted."""
    outbox_retention_interval_seconds: float = Field(default=3600.0, gt=0)
    worker_sweep_interval_seconds: float = Field(default=5.0, gt=0)
    """How often the worker sweeps the queue when idle, so a request whose run message was lost
    waits at most this long (`di1.platform.messaging.consumer.JobLoop`)."""

    # --- Worker heartbeat (`di1.platform.observability.heartbeat`, `di1.workers.healthcheck`) ---
    heartbeat_file: Path | None = None
    """No file, no heartbeat (and the health check reports unhealthy)."""
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0)
    heartbeat_max_age_seconds: float = Field(default=30.0, gt=0)

    # --- Logging, configured once at each process's startup ---------------------------------
    log_level: LogLevel = "INFO"

    @field_validator("database_url")
    @classmethod
    def _async_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        try:
            driver = make_url(value.get_secret_value()).drivername
        except ArgumentError:
            driver = None
        if driver != DATABASE_DRIVER:
            raise ValueError(f"must be a {DATABASE_DRIVER}:// URL")
        return value

    @field_validator("rabbitmq_url")
    @classmethod
    def _amqp_scheme(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        scheme, separator, _ = value.get_secret_value().partition("://")
        if not separator or scheme not in BROKER_SCHEMES:
            raise ValueError("must be an amqp:// or amqps:// URL")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    def broker_url(self) -> SecretStr:
        """``RABBITMQ_URL``, for the processes that use the broker; `MissingSettingError` when
        it is not set."""
        if self.rabbitmq_url is None:
            raise MissingSettingError("RABBITMQ_URL is not set")
        return self.rabbitmq_url
