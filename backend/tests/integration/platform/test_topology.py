"""The topology is durable: one command exchange and quorum queues bound to their message types,
with no dead-letter queue and no delivery limit (the worker acknowledges every delivery and its
sweep covers a lost message).

interfaces.md "Transaction boundaries" 7; plan §5 H.
"""

from __future__ import annotations

import asyncio

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from di1.platform.messaging.topology import Topology, declare_exchange, declare_queue
from tests.support.broker import queue_spec
from tests.support.waits import eventually


async def test_the_topology_is_a_durable_exchange_and_quorum_queue(
    broker: AbstractRobustConnection, topology: Topology
) -> None:
    channel = await broker.channel()
    spec = queue_spec(topology, "test.command")

    queue = await declare_queue(channel, topology, spec)

    # A passive declaration fails unless the exchange exists with these properties.
    await channel.declare_exchange(
        topology.exchange, aio_pika.ExchangeType.DIRECT, durable=True, passive=True
    )
    assert queue.durable
    assert queue.arguments == {"x-queue-type": "quorum"}


async def test_declaring_twice_is_harmless(
    broker: AbstractRobustConnection, topology: Topology
) -> None:
    """Every process declares the topology at startup."""
    channel = await broker.channel()
    spec = queue_spec(topology, "test.command")

    for _ in range(2):
        await declare_exchange(channel, topology)
        await declare_queue(channel, topology, spec)


async def test_a_queue_receives_only_its_message_types(
    broker: AbstractRobustConnection, topology: Topology
) -> None:
    channel = await broker.channel()
    work = await declare_queue(channel, topology, queue_spec(topology, "test.command"))
    await declare_queue(channel, topology, queue_spec(topology, "other.command", name="other"))
    exchange = await declare_exchange(channel, topology)

    for key in ("test.command", "other.command"):
        await exchange.publish(aio_pika.Message(body=key.encode()), routing_key=key)

    received: list[bytes] = []

    async def take(message: AbstractIncomingMessage) -> None:
        received.append(message.body)
        await message.ack()

    await work.consume(take)
    await eventually(lambda: bool(received))
    # A window in which nothing may happen: there is no event to wait for.
    await asyncio.sleep(0.2)
    assert received == [b"test.command"]
