"""The durable RabbitMQ topology: one command exchange and the queues a consumer declares.

- Commands go to a durable direct exchange with the envelope's ``message_type`` as routing key.
  Plan §0: no queue per module and no message per asset or per day; the consumer that owns a
  command type declares its queue and binds it to that type.
- Queues are quorum queues (replicated, durable). There is no dead-letter queue and no delivery
  limit: the worker acknowledges every delivery, a message being only a hint, and its periodic
  sweep takes any work whose message was lost (`di1.platform.messaging.consumer`).
"""

from __future__ import annotations

from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue


@dataclass(frozen=True, slots=True)
class Topology:
    exchange: str = "di1.commands"


@dataclass(frozen=True, slots=True)
class QueueSpec:
    name: str
    routing_keys: tuple[str, ...]
    """The message types the queue receives."""


async def declare_exchange(channel: AbstractChannel, topology: Topology) -> AbstractExchange:
    """Declare the command exchange (idempotent) and return it."""
    return await channel.declare_exchange(
        topology.exchange, aio_pika.ExchangeType.DIRECT, durable=True
    )


async def declare_queue(
    channel: AbstractChannel, topology: Topology, spec: QueueSpec
) -> AbstractQueue:
    """Declare ``spec``'s quorum queue, bound to the command exchange (idempotent), and return
    it."""
    exchange = await declare_exchange(channel, topology)
    queue = await channel.declare_queue(
        spec.name, durable=True, arguments={"x-queue-type": "quorum"}
    )
    for routing_key in spec.routing_keys:
        await queue.bind(exchange, routing_key)
    return queue
