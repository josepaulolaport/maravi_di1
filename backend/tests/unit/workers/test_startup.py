"""The worker processes fail at startup, with status 1 and without a secret in the logs, when
their settings are invalid or the broker URL they need is missing (staff review P5)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from pydantic import SecretStr

from di1.platform.config import MissingSettingError, Settings
from di1.platform.messaging.worker import WorkerPlugin, WorkerResources
from di1.workers.lifecycle import run_process
from di1.workers.main import run_worker
from di1.workers.outbox_relay import run_outbox_relay

PASSWORD = "s3cret-pw"


@pytest.fixture(autouse=True)
def no_broker_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the process environment: a ``RABBITMQ_URL`` set there must not hide the
    missing-URL failures below."""
    monkeypatch.delenv("RABBITMQ_URL", raising=False)


DATABASE_URL = f"postgresql+psycopg://di1:{PASSWORD}@db:5432/di1"


def test_invalid_settings_end_the_process_with_status_1_and_no_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://di1:{PASSWORD}@db:5432/di1")
    monkeypatch.setenv("RABBITMQ_URL", f"http://di1:{PASSWORD}@broker/")
    ran: list[Settings] = []

    async def run(settings: Settings, stop: asyncio.Event) -> None:
        ran.append(settings)

    with pytest.raises(SystemExit) as exited, caplog.at_level(logging.ERROR):
        run_process("test worker", run, logging.getLogger("test"))

    assert exited.value.code == 1
    assert ran == []
    assert "test worker: invalid settings" in caplog.text
    assert PASSWORD not in caplog.text


def _no_plugin(resources: WorkerResources) -> WorkerPlugin:
    raise AssertionError("the worker must fail before it builds anything")


async def test_the_worker_needs_the_broker_url() -> None:
    settings = Settings(database_url=SecretStr(DATABASE_URL))

    with pytest.raises(MissingSettingError, match="RABBITMQ_URL is not set"):
        await run_worker(settings, build=_no_plugin, stop=asyncio.Event())


async def test_the_outbox_relay_needs_the_broker_url() -> None:
    settings = Settings(database_url=SecretStr(DATABASE_URL))

    with pytest.raises(MissingSettingError, match="RABBITMQ_URL is not set"):
        await run_outbox_relay(settings, queues=(), stop=asyncio.Event())
