"""After the broker drops the connection, the robust connection comes back and consuming and
publishing resume by themselves.

interfaces.md "Transaction boundaries" 7 (relay and workers recover); plan §5 H (reconnect).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from aio_pika.abc import AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.connection import connect
from di1.platform.messaging.consumer import open_consumer_channel
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology, declare_queue
from tests.integration.platform.support import RecordingHandler, consuming, effects, make_envelope
from tests.support.broker import close_connections, eventually, queue_spec


@pytest.fixture
async def dropped_connection(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> AsyncIterator[tuple[AbstractRobustConnection, str]]:
    """A connection of the test's own; ``broker`` deletes the test's topology afterwards."""
    name = f"{topology.exchange}.reconnect"
    connection = await connect(broker_settings, connection_name=name)
    try:
        yield connection, name
    finally:
        await connection.close()


async def test_consuming_and_publishing_resume_after_a_reconnect(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker_settings: BrokerSettings,
    topology: Topology,
    management_url: str,
    dropped_connection: tuple[AbstractRobustConnection, str],
) -> None:
    connection, name = dropped_connection
    reconnected = asyncio.Event()
    connection.reconnect_callbacks.add(lambda *_: reconnected.set())
    channel = await open_consumer_channel(connection)
    own_queue = await declare_queue(channel, topology, queue_spec(topology, "test.command"))
    handler = RecordingHandler(unit_of_work_factory(session_factory))
    async with consuming(own_queue, handler):
        publisher = await MessagePublisher.create(connection, topology, settings=broker_settings)
        before, after = make_envelope(), make_envelope()
        await publisher.publish(before)
        await eventually(lambda: len(handler.calls) == 1)

        assert await close_connections(management_url, name) >= 1
        await asyncio.wait_for(reconnected.wait(), timeout=30)
        await publisher.publish(after)

        await eventually(lambda: len(handler.calls) == 2, within=30)
    assert handler.calls == [before.message_id, after.message_id]
    assert sorted(await effects(engine)) == sorted([before.message_id, after.message_id])
