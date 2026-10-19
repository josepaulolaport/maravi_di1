"""Fixtures for the platform integration tests: a fresh, migrated PostgreSQL database per test,
and a RabbitMQ connection with a topology of the test's own."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from aio_pika.abc import AbstractRobustConnection
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings, Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.messaging.connection import connect
from di1.platform.messaging.topology import QueueSpec, Topology, dead_letter_queue_name
from tests.integration.databases import fresh_database_url

BACKEND = Path(__file__).resolve().parents[3]


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from fresh_database_url()


@pytest.fixture
def migrated_database_url(database_url: str) -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
def settings(migrated_database_url: str) -> Settings:
    return Settings(database_url=SecretStr(migrated_database_url))


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def broker_settings() -> BrokerSettings:
    """``TEST_RABBITMQ_URL`` is a test broker (``amqp://guest:guest@127.0.0.1:5672/``). Without
    it the broker tests are skipped and reported, so **not verified**; with
    ``REQUIRE_BROKER_TESTS=1`` a missing variable fails the run instead."""
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        if os.environ.get("REQUIRE_BROKER_TESTS") == "1":
            pytest.fail("REQUIRE_BROKER_TESTS=1 but TEST_RABBITMQ_URL is not set")
        pytest.skip("TEST_RABBITMQ_URL is not set: broker tests not run")
    return BrokerSettings(
        rabbitmq_url=SecretStr(url),
        rabbitmq_delivery_limit=2,
        rabbitmq_retry_base_delay_seconds=0.2,
        rabbitmq_retry_max_delay_seconds=1,
        rabbitmq_publish_timeout_seconds=5,
    )


@pytest.fixture
def management_url() -> str:
    """``TEST_RABBITMQ_MANAGEMENT_URL`` (``http://guest:guest@127.0.0.1:15672``): the reconnect
    test closes connections through the management API."""
    url = os.environ.get("TEST_RABBITMQ_MANAGEMENT_URL")
    if not url:
        if os.environ.get("REQUIRE_BROKER_TESTS") == "1":
            pytest.fail("REQUIRE_BROKER_TESTS=1 but TEST_RABBITMQ_MANAGEMENT_URL is not set")
        pytest.skip("TEST_RABBITMQ_MANAGEMENT_URL is not set: reconnect test not run")
    return url


@pytest.fixture
def topology() -> Topology:
    """Names of this test's own, so tests never share broker state."""
    prefix = f"test.{uuid.uuid4().hex[:12]}"
    return Topology(exchange=f"{prefix}.commands", dead_letter_exchange=f"{prefix}.dead-letter")


@pytest.fixture
async def broker(
    broker_settings: BrokerSettings, topology: Topology
) -> AsyncIterator[AbstractRobustConnection]:
    connection = await connect(broker_settings, connection_name=f"{topology.exchange}.test")
    try:
        yield connection
    finally:
        await _delete_topology(connection, topology)
        await connection.close()


async def _delete_topology(connection: AbstractRobustConnection, topology: Topology) -> None:
    channel = await connection.channel()
    for queue in TEST_QUEUES:
        for name in (queue, dead_letter_queue_name(queue)):
            await channel.queue_delete(f"{topology.exchange}.{name}")
    await channel.exchange_delete(topology.exchange)
    await channel.exchange_delete(topology.dead_letter_exchange)
    await channel.close()


TEST_QUEUES = ("work", "other")
"""Queue names the broker tests use, prefixed by their topology's exchange name."""


def queue_spec(topology: Topology, *routing_keys: str, name: str = "work") -> QueueSpec:
    assert name in TEST_QUEUES, "add the name to TEST_QUEUES so the test deletes it"
    return QueueSpec(name=f"{topology.exchange}.{name}", routing_keys=routing_keys)
