"""Process settings, read from the environment (plan §3, Wave 0).

Every value comes from configuration (OQ-5). Secrets are `SecretStr` and validation errors never
echo their input, so a URL with a password never reaches a log or a traceback.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_DRIVER = "postgresql+psycopg"


class Settings(BaseSettings):
    """Settings shared by the API and the workers. Environment names are the field names in
    upper case (``DATABASE_URL``, ``DATABASE_POOL_SIZE``, ...)."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    """SQLAlchemy URL, ``postgresql+psycopg://user:password@host:port/database``."""
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_echo: bool = False

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
