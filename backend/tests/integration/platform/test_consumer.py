"""The consumer acknowledges only after its state change commits, handles each message once
however often it is delivered, and retries transient failures up to the delivery limit.

interfaces.md "Transaction boundaries" 7 (at-least-once; inbox idempotency; ACK only after the
durable state transition; retries for transient failures only); plan §5 H (duplicate delivery,
ACK after durability). The reconnect is in test_reconnect.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import cast

import pytest
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.platform.messaging.consumer import (
    MessageConsumer,
    open_consumer_channel,
)
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology, dead_letter_queue_name, declare_queue
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import (
    EFFECT,
    RecordingHandler,
    effects,
    eventually,
    has_effects,
    make_consumer,
    make_envelope,
)


@dataclass
class _FakeDelivery:
    """An incoming message that checks, when it is settled, what is already durable."""

    body: bytes
    engine: AsyncEngine
    message_id: str | None = None
    headers: dict[str, object] = field(default_factory=dict)
    settled: list[tuple[str, list[uuid.UUID]]] = field(default_factory=list)

    async def ack(self) -> None:
        self.settled.append(("ack", await effects(self.engine)))

    async def nack(self, requeue: bool = True) -> None:
        self.settled.append((f"nack requeue={requeue}", await effects(self.engine)))

    async def reject(self, requeue: bool = False) -> None:
        self.settled.append((f"reject requeue={requeue}", await effects(self.engine)))


async def _deliver(consumer: MessageConsumer, delivery: _FakeDelivery) -> None:
    await consumer.handle(cast(AbstractIncomingMessage, delivery))


# Ordering of the acknowledgement, checked delivery by delivery (no broker needed).


async def test_the_ack_comes_after_the_state_change_is_durable(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)

    await _deliver(make_consumer(session_factory, RecordingHandler()), delivery)

    assert delivery.settled == [("ack", [envelope.message_id])]


async def test_a_handler_that_commits_itself_is_not_committed_twice(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)

    await _deliver(make_consumer(session_factory, RecordingHandler(commits_itself=True)), delivery)

    assert delivery.settled == [("ack", [envelope.message_id])]


async def test_a_transient_failure_rolls_back_and_returns_the_message(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)

    await _deliver(make_consumer(session_factory, RecordingHandler(failures=1)), delivery)

    assert delivery.settled == [("nack requeue=True", [])]


async def test_a_permanent_failure_rolls_back_and_dead_letters(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)

    await _deliver(
        make_consumer(session_factory, RecordingHandler(failures=1, permanent=True)), delivery
    )

    assert delivery.settled == [("reject requeue=False", [])]


async def test_a_duplicate_is_acked_without_running_the_handler(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    envelope = make_envelope()
    handler = RecordingHandler()
    consumer = make_consumer(session_factory, handler)

    first, second = (_FakeDelivery(envelope.to_json(), engine) for _ in range(2))
    await _deliver(consumer, first)
    await _deliver(consumer, second)

    assert handler.calls == [envelope.message_id]
    assert second.settled == [("ack", [envelope.message_id])]


async def test_a_failed_first_delivery_is_handled_on_redelivery(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """The inbox record rolled back with the failure, so the redelivery is not a duplicate."""
    envelope = make_envelope()
    handler = RecordingHandler(failures=1)
    consumer = make_consumer(session_factory, handler)

    for _ in range(2):
        await _deliver(consumer, _FakeDelivery(envelope.to_json(), engine))

    assert handler.calls == [envelope.message_id, envelope.message_id]
    assert await effects(engine) == [envelope.message_id]


@pytest.mark.parametrize("body", [b"not json", b'{"message_id": "x"}', b'{"payload": 1.5}'])
async def test_a_body_that_is_not_an_envelope_is_dead_lettered(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine, body: bytes
) -> None:
    handler = RecordingHandler()
    delivery = _FakeDelivery(body, engine)

    await _deliver(make_consumer(session_factory, handler), delivery)

    assert handler.calls == []
    assert delivery.settled == [("reject requeue=False", [])]


# End to end through RabbitMQ.


@pytest.fixture
async def queue(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> AbstractQueue:
    channel = await open_consumer_channel(broker, broker_settings)
    return await declare_queue(
        channel, topology, queue_spec(topology, "test.command"), settings=broker_settings
    )


@pytest.fixture
async def publisher(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> MessagePublisher:
    return await MessagePublisher.create(broker, topology, settings=broker_settings)


async def _queue_depth(queue: AbstractQueue) -> int:
    declared = await queue.channel.declare_queue(queue.name, passive=True)
    return declared.declaration_result.message_count or 0


async def _dead_letters(broker: AbstractRobustConnection, queue: AbstractQueue) -> list[Envelope]:
    channel = await broker.channel()
    dead = await channel.declare_queue(dead_letter_queue_name(queue.name), passive=True)
    received: list[Envelope] = []
    async with asyncio.timeout(10):
        while not received:
            while (message := await dead.get(fail=False)) is not None:
                await message.ack()
                received.append(Envelope.from_json(message.body))
            await asyncio.sleep(0.05)
    return received


async def test_a_duplicate_delivery_is_handled_once(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker_settings: BrokerSettings,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """The relay resent a message after a crash (test_outbox_relay): same ``message_id``."""
    envelope = make_envelope()
    handler = RecordingHandler()
    await make_consumer(session_factory, handler, broker_settings).start(queue)

    await publisher.publish(envelope)
    await publisher.publish(envelope)

    await eventually(lambda: len(handler.calls) == 1)
    await asyncio.sleep(0.3)
    assert handler.calls == [envelope.message_id]
    assert await effects(engine) == [envelope.message_id]
    assert await _queue_depth(queue) == 0


async def test_a_transient_failure_is_retried_by_the_broker(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker_settings: BrokerSettings,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    envelope = make_envelope()
    handler = RecordingHandler(failures=1)
    await make_consumer(session_factory, handler, broker_settings).start(queue)

    await publisher.publish(envelope)

    await eventually(lambda: len(handler.calls) == 2)
    await eventually(lambda: has_effects(engine, [envelope.message_id]))
    assert handler.calls == [envelope.message_id, envelope.message_id]


async def test_a_message_failing_past_the_delivery_limit_is_dead_lettered(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_settings: BrokerSettings,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    envelope = make_envelope()
    handler = RecordingHandler(failures=1000)
    await make_consumer(session_factory, handler, broker_settings).start(queue)

    await publisher.publish(envelope)

    assert await _dead_letters(broker, queue) == [envelope]
    assert len(handler.calls) == broker_settings.rabbitmq_delivery_limit + 1
    assert await effects(engine) == []


async def test_a_permanent_failure_is_dead_lettered_at_once(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker_settings: BrokerSettings,
    broker: AbstractRobustConnection,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    envelope = make_envelope()
    handler = RecordingHandler(failures=1, permanent=True)
    await make_consumer(session_factory, handler, broker_settings).start(queue)

    await publisher.publish(envelope)

    assert await _dead_letters(broker, queue) == [envelope]
    assert handler.calls == [envelope.message_id]
    assert await effects(engine) == []


@dataclass
class _FailsFor:
    """A dependency is down for ``seconds`` (a database restart): fails until then."""

    seconds: float
    calls: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._until = time.monotonic() + self.seconds

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> None:
        self.calls.append(time.monotonic())
        if time.monotonic() < self._until:
            raise RuntimeError("database restarting")
        await uow.session.execute(EFFECT, {"m": envelope.message_id})


async def test_a_short_outage_is_outlasted_by_the_retry_pauses(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker_settings: BrokerSettings,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """Without the pauses, all ``delivery_limit + 1`` attempts fail within milliseconds and the
    command is dead-lettered; with them (0.2 s, then 0.4 s) the third attempt succeeds."""
    envelope = make_envelope()
    handler = _FailsFor(seconds=0.4)
    consumer = MessageConsumer(
        consumer_name="worker",
        handler=handler,
        uow_factory=unit_of_work_factory(session_factory),
        settings=broker_settings,
    )
    await consumer.start(queue)

    await publisher.publish(envelope)

    await eventually(lambda: has_effects(engine, [envelope.message_id]))
    assert len(handler.calls) == 3
    gaps = [later - earlier for earlier, later in itertools.pairwise(handler.calls)]
    assert gaps[0] >= 0.2 and gaps[1] >= 0.4
