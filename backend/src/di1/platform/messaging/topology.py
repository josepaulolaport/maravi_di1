"""The durable RabbitMQ topology: one command exchange, one dead-letter exchange, and the queues
a consumer declares.

- Commands go to a durable direct exchange with the envelope's ``message_type`` as routing key.
  Plan §0: no queue per module and no message per job; the consumer that owns a command type
  declares its queue and binds it to that type.
- Queues are quorum queues (replicated, durable). The retry policy is the broker's delivery
  limit: a delivery the consumer returns to the queue (a transient failure) is retried up to
  ``rabbitmq_delivery_limit`` times; then, or at once when the consumer rejects it as
  permanent, the broker dead-letters it to ``<queue>.dead-letter`` for inspection. The pause
  between retries is the consumer's (`di1.platform.messaging.consumer`). Missing
  prices are not failures and are never retried (interfaces.md "Transaction boundaries" 7).
"""

from __future__ import annotations

from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue, FieldValue

from di1.platform.config import BrokerSettings


@dataclass(frozen=True, slots=True)
class Topology:
    exchange: str = "di1.commands"
    dead_letter_exchange: str = "di1.dead-letter"


@dataclass(frozen=True, slots=True)
class QueueSpec:
    name: str
    routing_keys: tuple[str, ...]
    """The message types the queue receives."""


def dead_letter_queue_name(queue_name: str) -> str:
    return f"{queue_name}.dead-letter"


async def declare_exchanges(channel: AbstractChannel, topology: Topology) -> AbstractExchange:
    """Declare both exchanges (idempotent) and return the command exchange."""
    await channel.declare_exchange(
        topology.dead_letter_exchange, aio_pika.ExchangeType.DIRECT, durable=True
    )
    return await channel.declare_exchange(
        topology.exchange, aio_pika.ExchangeType.DIRECT, durable=True
    )


async def declare_queue(
    channel: AbstractChannel, topology: Topology, spec: QueueSpec, *, settings: BrokerSettings
) -> AbstractQueue:
    """Declare ``spec``'s queue and its dead-letter queue, bound to their exchanges
    (idempotent), and return the queue."""
    exchange = await declare_exchanges(channel, topology)
    dead_letter_exchange = await channel.get_exchange(topology.dead_letter_exchange)
    dead_letters = await channel.declare_queue(
        dead_letter_queue_name(spec.name), durable=True, arguments={"x-queue-type": "quorum"}
    )
    queue = await channel.declare_queue(
        spec.name, durable=True, arguments=queue_arguments(topology, spec, settings=settings)
    )
    await dead_letters.bind(dead_letter_exchange, spec.name)
    for routing_key in spec.routing_keys:
        await queue.bind(exchange, routing_key)
    return queue


def queue_arguments(
    topology: Topology, spec: QueueSpec, *, settings: BrokerSettings
) -> dict[str, FieldValue]:
    """A quorum queue whose dead letters go, routed by the queue's own name, to its dead-letter
    queue only (two queues may consume the same message type). Dead-lettering is at least once,
    which quorum queues require ``reject-publish`` overflow for; no length limit is set."""
    return {
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": topology.dead_letter_exchange,
        "x-dead-letter-routing-key": spec.name,
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
        "x-delivery-limit": settings.rabbitmq_delivery_limit,
    }
