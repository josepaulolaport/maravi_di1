"""The topology is durable, with a dead-letter queue per queue and the broker's delivery limit
as the retry policy.

interfaces.md "Transaction boundaries" 7 (retries for transient failures only); plan §5 H
(retry and failure policy).
"""

from __future__ import annotations

import asyncio

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection

from di1.platform.config import BrokerSettings
from di1.platform.messaging.topology import (
    Topology,
    dead_letter_queue_name,
    declare_exchanges,
    declare_queue,
)
from tests.integration.platform.conftest import queue_spec


async def test_the_topology_is_durable_with_a_dead_letter_queue(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> None:
    channel = await broker.channel()
    spec = queue_spec(topology, "test.command")

    await declare_exchanges(channel, topology)
    queue = await declare_queue(channel, topology, spec, settings=broker_settings)

    # Passive declarations fail unless the entities exist with these properties.
    await channel.declare_exchange(
        topology.exchange, aio_pika.ExchangeType.DIRECT, durable=True, passive=True
    )
    await channel.declare_exchange(
        topology.dead_letter_exchange, aio_pika.ExchangeType.DIRECT, durable=True, passive=True
    )
    await channel.declare_queue(dead_letter_queue_name(spec.name), passive=True)
    assert queue.durable
    assert queue.arguments == {
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": topology.dead_letter_exchange,
        "x-dead-letter-routing-key": spec.name,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
        "x-delivery-limit": broker_settings.rabbitmq_delivery_limit,
    }


async def test_declaring_twice_is_harmless(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> None:
    """Every process declares the topology at startup."""
    channel = await broker.channel()
    spec = queue_spec(topology, "test.command")

    for _ in range(2):
        await declare_exchanges(channel, topology)
        await declare_queue(channel, topology, spec, settings=broker_settings)


async def test_a_dead_letter_goes_only_to_its_own_queue_dead_letter_queue(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> None:
    """Two queues consume the same message type; one rejects its copy."""
    channel = await broker.channel()
    work = await declare_queue(
        channel, topology, queue_spec(topology, "test.command"), settings=broker_settings
    )
    other_spec = queue_spec(topology, "test.command", name="other")
    other = await declare_queue(channel, topology, other_spec, settings=broker_settings)
    exchange = await declare_exchanges(channel, topology)
    await exchange.publish(aio_pika.Message(b"{}"), routing_key="test.command")

    rejected = await work.get(timeout=5)
    assert rejected is not None
    await rejected.reject(requeue=False)

    work_dead = await channel.declare_queue(dead_letter_queue_name(work.name), passive=True)
    assert await _next_message(work_dead) is not None  # at-least-once dead-lettering is async
    other_dead = await channel.declare_queue(dead_letter_queue_name(other_spec.name), passive=True)
    assert await other_dead.get(timeout=5, fail=False) is None
    assert await other.get(timeout=5, fail=False) is not None


async def _next_message(queue: AbstractQueue) -> AbstractIncomingMessage | None:
    for _ in range(100):
        if (message := await queue.get(fail=False)) is not None:
            return message
        await asyncio.sleep(0.05)
    return None
