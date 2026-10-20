"""Fixtures for the platform integration tests: a fresh, migrated PostgreSQL database per test,
and a RabbitMQ connection with a topology of the test's own."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from aio_pika.abc import AbstractRobustConnection
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.platform.config import BrokerSettings, Settings
from di1.platform.database.engine import create_engine
from di1.platform.messaging.connection import connect
from di1.platform.messaging.topology import QueueSpec, Topology
from tests.integration.platform.support import CREATE_EFFECTS


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
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        if os.environ.get("REQUIRE_BROKER_TESTS") == "1":
            pytest.fail("REQUIRE_BROKER_TESTS=1 but TEST_RABBITMQ_URL is not set")
        pytest.skip("TEST_RABBITMQ_URL is not set: broker tests not run")
    return BrokerSettings(
        rabbitmq_url=SecretStr(url),
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
    return Topology(exchange=f"{prefix}.commands")


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
        await channel.queue_delete(f"{topology.exchange}.{queue}")
    await channel.exchange_delete(topology.exchange)
    await channel.close()


TEST_QUEUES = ("work", "other")
"""Queue names the broker tests use, prefixed by their topology's exchange name."""


def queue_spec(topology: Topology, *routing_keys: str, name: str = "work") -> QueueSpec:
    assert name in TEST_QUEUES, "add the name to TEST_QUEUES so the test deletes it"
    return QueueSpec(name=f"{topology.exchange}.{name}", routing_keys=routing_keys)
