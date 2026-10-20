"""Fixtures for the platform integration tests: a fresh, migrated PostgreSQL database per test,
and a RabbitMQ connection with a topology of the test's own."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from aio_pika.abc import AbstractRobustConnection
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.config import BrokerSettings, Settings
from di1.platform.database.engine import create_engine
from di1.platform.messaging.connection import connect
from di1.platform.messaging.topology import Topology
from tests.integration.platform.support import CREATE_EFFECTS
from tests.support.broker import SilentServer, broker_url, delete_topology, silent_server


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """The test's database, with the handlers' ``public.test_effects`` table."""
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.execute(CREATE_EFFECTS)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def broker_settings() -> BrokerSettings:
    """``TEST_RABBITMQ_URL`` is a test broker (``amqp://guest:guest@127.0.0.1:5672/``). Without
    it the broker tests are skipped and reported, so **not verified**; with
    ``REQUIRE_BROKER_TESTS=1`` a missing variable fails the run instead."""
    return BrokerSettings(
        rabbitmq_url=SecretStr(broker_url()),
        rabbitmq_publish_timeout_seconds=5,
    )


@pytest.fixture
def management_url() -> str:
    """``TEST_RABBITMQ_MANAGEMENT_URL`` (``http://guest:guest@127.0.0.1:15672``): the reconnect
    test closes connections through the management API."""
    return broker_url("TEST_RABBITMQ_MANAGEMENT_URL")


@pytest.fixture
def topology() -> Topology:
    """Names of this test's own, so tests never share broker state."""
    prefix = f"test.{uuid.uuid4().hex[:12]}"
    return Topology(exchange=f"{prefix}.commands")


@pytest.fixture
async def broker(
    broker_settings: BrokerSettings, topology: Topology
) -> AsyncIterator[AbstractRobustConnection]:
    connection = await connect(broker_settings, connection_name=f"{topology.exchange}.test")
    try:
        yield connection
    finally:
        await delete_topology(connection, topology)
        await connection.close()


@pytest.fixture
async def silent() -> AsyncIterator[SilentServer]:
    async with silent_server() as server:
        yield server


@pytest.fixture
def hanging_broker_url(silent: SilentServer) -> str:
    """A broker that accepts the connection and never answers."""
    return f"amqp://guest:s3cret-pw@127.0.0.1:{silent.port}/"


@pytest.fixture
def hanging_database_settings(silent: SilentServer) -> Settings:
    """A database that accepts the connection and never answers."""
    return Settings(
        database_url=SecretStr(f"postgresql+psycopg://u:s3cret-pw@127.0.0.1:{silent.port}/db")
    )
