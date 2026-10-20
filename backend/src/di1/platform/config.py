"""Process settings, read from the environment (plan §3, Wave 0).

Every value comes from configuration (OQ-5): the process environment, else the `.env` files in
`ENV_FILES`, else the field's default. Secrets are `SecretStr` and validation errors never
echo their input, so a URL with a password never reaches a log or a traceback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_DRIVER = "postgresql+psycopg"

ENV_FILES = ("../.env", ".env")
"""Read relative to the working directory, ``backend/`` for every ``uv run``: the repository
root's `.env` (the one Compose interpolates), then ``backend/.env``, which wins over it. A missing
file is skipped; in the image neither exists, and Compose sets the environment."""


class Settings(BaseSettings):
    """Settings shared by the API and the workers. Environment names are the field names in
    upper case (``DATABASE_URL``, ``DATABASE_POOL_SIZE``, ...)."""

    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
    )

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


def get_settings() -> Settings:
    """Read the settings from the environment now (never at import time)."""
    return Settings()


BROKER_SCHEMES = ("amqp", "amqps")


class BrokerSettings(BaseSettings):
    """RabbitMQ settings, read only by the processes that use the broker (the outbox relay and
    the workers): an HTTP write never publishes, so the API does not need them."""

    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
    )

    rabbitmq_url: SecretStr
    """``amqp://user:password@host:port/vhost``."""
    rabbitmq_prefetch_count: int = Field(default=1, ge=1)
    """Unacknowledged deliveries per consumer."""
    rabbitmq_delivery_limit: int = Field(default=5, ge=1)
    """Redeliveries of a failing message before the broker dead-letters it."""
    rabbitmq_retry_base_delay_seconds: float = Field(default=1.0, gt=0)
    """Pause before a failed delivery returns to the queue, doubled on each redelivery, so a
    short outage (a database restart) does not exhaust the delivery limit."""
    rabbitmq_retry_max_delay_seconds: float = Field(default=30.0, gt=0)
    rabbitmq_publish_timeout_seconds: float = Field(default=10.0, gt=0)
    outbox_relay_batch_size: int = Field(default=100, ge=1)
    outbox_relay_poll_interval_seconds: float = Field(default=1.0, gt=0)
    outbox_relay_retry_base_delay_seconds: float = Field(default=1.0, gt=0)
    """Pause before the relay retries a row it failed to publish, doubled on each attempt, so a
    failing row is not retried on every poll."""
    outbox_relay_retry_max_delay_seconds: float = Field(default=60.0, gt=0)
    inbox_retention_days: int = Field(default=7, ge=1)
    """Inbox records older than this are deleted by the outbox relay (user decision M9)."""
    inbox_retention_interval_seconds: float = Field(default=3600.0, gt=0)
    outbox_retention_days: int = Field(default=7, ge=1)
    """Outbox rows published longer ago than this are deleted by the outbox relay; an
    unpublished row is never deleted."""
    outbox_retention_interval_seconds: float = Field(default=3600.0, gt=0)

    @field_validator("rabbitmq_url")
    @classmethod
    def _amqp_scheme(cls, value: SecretStr) -> SecretStr:
        scheme, separator, _ = value.get_secret_value().partition("://")
        if not separator or scheme not in BROKER_SCHEMES:
            raise ValueError("must be an amqp:// or amqps:// URL")
        return value


def get_broker_settings() -> BrokerSettings:
    """Read the broker settings from the environment now (never at import time)."""
    return BrokerSettings()


class HeartbeatSettings(BaseSettings):
    """The heartbeat file of a worker process (`di1.platform.observability.heartbeat`) and its
    health check (`di1.workers.healthcheck`), which read the same variables. No file, no
    heartbeat."""

    model_config = SettingsConfigDict(
        frozen=True, extra="ignore", env_file=ENV_FILES, env_file_encoding="utf-8"
    )

    heartbeat_file: Path | None = None
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0)
    heartbeat_max_age_seconds: float = Field(default=30.0, gt=0)


def get_heartbeat_settings() -> HeartbeatSettings:
    """Read the heartbeat settings from the environment now (never at import time)."""
    return HeartbeatSettings()


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingSettings(BaseSettings):
    """Logging, configured once at each process's startup (`di1.platform.observability`)."""

    model_config = SettingsConfigDict(
        frozen=True, extra="ignore", env_file=ENV_FILES, env_file_encoding="utf-8"
    )

    log_level: LogLevel = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


def get_logging_settings() -> LoggingSettings:
    """Read the logging settings from the environment now (never at import time)."""
    return LoggingSettings()
