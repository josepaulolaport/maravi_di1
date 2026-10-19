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
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import pytest
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.platform.messaging.consumer import (
    AfterAck,
    AfterAckRunner,
    MessageConsumer,
    MessageHandler,
    open_consumer_channel,
)
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology, dead_letter_queue_name, declare_queue
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import (
    EFFECT,
    FAST_RETRIES,
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
    """A dependency is down for ``seconds`` from the first delivery on (a database restart).

    The outage starts at the first call, not when the handler is built, so the broker set-up
    before the first delivery cannot use up part of it on a slow machine."""

    seconds: float
    calls: list[float] = field(default_factory=list)

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> None:
        now = time.monotonic()
        self.calls.append(now)
        if now < self.calls[0] + self.seconds:
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


# Work after the acknowledgement (the processing run: the claim commits, the message is acked,
# then the per-date run goes on with its own Units of Work; plan §7, lane G Wave 4 plan point 2).
# The work runs in the runner's task, not in the broker's delivery task, so a channel that
# closes does not cancel a run that no longer depends on the broker.


@dataclass
class _ClaimThenRun:
    """Writes the effect (the claim) and returns the work to run once the message is acked."""

    delivery: _FakeDelivery | None = None
    fails: bool = False
    hold: asyncio.Event | None = None
    calls: list[uuid.UUID] = field(default_factory=list)
    started: list[uuid.UUID] = field(default_factory=list)
    ran: list[tuple[uuid.UUID, list[str]]] = field(default_factory=list)
    cancelled: list[uuid.UUID] = field(default_factory=list)

    async def __call__(self, envelope: Envelope, *, uow: UnitOfWork) -> AfterAck:
        self.calls.append(envelope.message_id)
        await uow.session.execute(EFFECT, {"m": envelope.message_id})

        async def run() -> None:
            self.started.append(envelope.message_id)
            if self.hold is not None:
                try:
                    await self.hold.wait()
                except asyncio.CancelledError:
                    self.cancelled.append(envelope.message_id)
                    raise
            settled = [] if self.delivery is None else [s for s, _ in self.delivery.settled]
            self.ran.append((envelope.message_id, settled))
            if self.fails:
                raise RuntimeError("the run failed")

        return run


def _consumer_with(
    session_factory: async_sessionmaker[AsyncSession],
    handler: MessageHandler,
    runner: AfterAckRunner,
) -> MessageConsumer:
    return MessageConsumer(
        consumer_name="worker",
        handler=handler,
        uow_factory=unit_of_work_factory(session_factory),
        settings=FAST_RETRIES,
        after_ack=runner,
    )


@pytest.fixture
async def runner() -> AsyncIterator[AfterAckRunner]:
    runner = AfterAckRunner()
    try:
        yield runner
    finally:
        await runner.stop()


async def test_the_work_after_the_ack_runs_once_the_message_is_acked(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)
    handler = _ClaimThenRun(delivery)

    await _deliver(_consumer_with(session_factory, handler, runner), delivery)
    await asyncio.wait_for(runner.wait_idle(), timeout=5)

    assert delivery.settled == [("ack", [envelope.message_id])]
    assert handler.ran == [(envelope.message_id, ["ack"])]


async def test_the_delivery_does_not_wait_for_the_work_after_the_ack(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
) -> None:
    """The run is not inside the broker's delivery task: that task ends at the ack."""
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)
    handler = _ClaimThenRun(delivery, hold=asyncio.Event())

    await asyncio.wait_for(
        _deliver(_consumer_with(session_factory, handler, runner), delivery), timeout=5
    )

    assert delivery.settled == [("ack", [envelope.message_id])]
    await eventually(lambda: handler.started == [envelope.message_id])
    assert handler.ran == []


async def test_a_failure_after_the_ack_is_logged_and_the_message_stays_acked(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    envelope = make_envelope()
    delivery = _FakeDelivery(envelope.to_json(), engine)

    await _deliver(
        _consumer_with(session_factory, _ClaimThenRun(delivery, fails=True), runner), delivery
    )
    await asyncio.wait_for(runner.wait_idle(), timeout=5)

    assert delivery.settled == [("ack", [envelope.message_id])]
    assert (
        f"work after the ack of message {envelope.message_id} (test.command) failed" in caplog.text
    )


async def test_a_duplicate_does_not_run_the_work_after_the_ack(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
) -> None:
    envelope = make_envelope()
    handler = _ClaimThenRun()
    consumer = _consumer_with(session_factory, handler, runner)

    for _ in range(2):
        await _deliver(consumer, _FakeDelivery(envelope.to_json(), engine))
    await asyncio.wait_for(runner.wait_idle(), timeout=5)

    assert [message_id for message_id, _ in handler.ran] == [envelope.message_id]


async def test_a_delivery_during_a_run_is_acked_at_once_and_its_run_waits(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
) -> None:
    """A second command (a duplicate resent by the relay) never sits unacked
    behind a run, where the broker's consumer timeout would close the channel; the runs
    themselves go one at a time (one run at a time per process)."""
    first, second = make_envelope(), make_envelope()
    handler = _ClaimThenRun(hold=asyncio.Event())
    consumer = _consumer_with(session_factory, handler, runner)
    first_delivery = _FakeDelivery(first.to_json(), engine)
    second_delivery = _FakeDelivery(second.to_json(), engine)

    await _deliver(consumer, first_delivery)
    await eventually(lambda: handler.started == [first.message_id])
    await asyncio.wait_for(_deliver(consumer, second_delivery), timeout=5)

    assert second_delivery.settled == [("ack", [first.message_id, second.message_id])]
    await asyncio.sleep(0.1)
    assert handler.started == [first.message_id]

    assert handler.hold is not None
    handler.hold.set()
    await asyncio.wait_for(runner.wait_idle(), timeout=5)
    assert [message_id for message_id, _ in handler.ran] == [first.message_id, second.message_id]


async def test_stopping_the_runner_cancels_the_run_and_drops_the_waiting_ones(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The worker's shutdown: the run in progress is cancelled (its open transaction rolls
    back); a waiting run is dropped, its start committed, and recovered when the worker starts
    again (OQ-45)."""
    first, second = make_envelope(), make_envelope()
    runner = AfterAckRunner()
    handler = _ClaimThenRun(hold=asyncio.Event())
    consumer = _consumer_with(session_factory, handler, runner)
    await _deliver(consumer, _FakeDelivery(first.to_json(), engine))
    await _deliver(consumer, _FakeDelivery(second.to_json(), engine))
    await eventually(lambda: handler.started == [first.message_id])

    await asyncio.wait_for(runner.stop(), timeout=5)

    assert handler.cancelled == [first.message_id]
    assert handler.started == [first.message_id]
    assert "1 waiting runs dropped" in caplog.text


@dataclass
class _AckFails(_FakeDelivery):
    async def ack(self) -> None:
        raise RuntimeError("channel closed")


async def test_the_work_after_the_ack_runs_even_when_the_ack_fails(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    runner: AfterAckRunner,
) -> None:
    """The run's start is committed: the redelivery will be an inbox duplicate without a run, so
    the run must go on now instead of waiting for the worker's next start."""
    envelope = make_envelope()
    handler = _ClaimThenRun()

    await _deliver(
        _consumer_with(session_factory, handler, runner),
        _AckFails(envelope.to_json(), engine),
    )
    await asyncio.wait_for(runner.wait_idle(), timeout=5)

    assert [message_id for message_id, _ in handler.ran] == [envelope.message_id]
