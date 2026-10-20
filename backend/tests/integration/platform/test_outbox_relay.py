"""The relay publishes committed outbox rows with confirms, marks them only after the confirm,
and resends whatever a crash or a broker failure left unmarked.

interfaces.md "Transaction boundaries" 3 (outbox relay publishes with confirms) and 7
(at-least-once; relay recovers after crashes); plan §5 H (simulated relay crash and resend).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from aio_pika.abc import AbstractQueue, AbstractRobustConnection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.config import BrokerSettings
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from di1.platform.messaging.envelope import Envelope
from di1.platform.messaging.inbox import InboxRetention
from di1.platform.messaging.outbox import OutboxRetention, add_outbox_message
from di1.platform.messaging.outbox_relay import OutboxRelay
from di1.platform.messaging.publisher import MessagePublisher
from di1.platform.messaging.topology import Topology, declare_queue
from tests.integration.platform.conftest import queue_spec
from tests.integration.platform.support import eventually


class _CrashError(BaseException):
    """The relay process dies (BaseException: nothing in the relay may swallow it)."""


class _CrashAfterPublish:
    """Publishes for real, then dies before the relay can mark the row."""

    def __init__(self, publisher: MessagePublisher) -> None:
        self._publisher = publisher

    async def publish(self, envelope: Envelope) -> None:
        await self._publisher.publish(envelope)
        raise _CrashError


async def _write(
    session_factory: async_sessionmaker[AsyncSession], *message_types: str
) -> list[Envelope]:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        envelopes = [
            await add_outbox_message(uow, message_type=message_type, payload={"n": index})
            for index, message_type in enumerate(message_types)
        ]
        await uow.commit()
    return envelopes


async def _state(engine: AsyncEngine) -> list[tuple[uuid.UUID, bool, int, str | None]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT message_id, published_at IS NOT NULL, publish_attempts, last_error"
                " FROM platform.outbox_messages ORDER BY id"
            )
        )
        return [(row[0], row[1], row[2], row[3]) for row in rows]


async def _drain(queue: AbstractQueue) -> list[Envelope]:
    received = []
    while (message := await queue.get(timeout=5, fail=False)) is not None:
        await message.ack()
        received.append(Envelope.from_json(message.body))
    return received


@pytest.fixture
async def queue(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> AbstractQueue:
    channel = await broker.channel()
    return await declare_queue(
        channel, topology, queue_spec(topology, "test.command"), settings=broker_settings
    )


@pytest.fixture
async def publisher(
    broker: AbstractRobustConnection, broker_settings: BrokerSettings, topology: Topology
) -> MessagePublisher:
    return await MessagePublisher.create(broker, topology, settings=broker_settings)


class _Clock:
    """An injected monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _relay(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: object,
    batch_size: int = 100,
    *,
    clock: _Clock | None = None,
) -> OutboxRelay:
    """With a ``clock``, failed rows wait 1 s, then 2 s, then 3 s at most; without one, the
    pauses are short enough for the tests that run the relay in real time."""
    return OutboxRelay(
        unit_of_work_factory(session_factory),
        publisher,  # type: ignore[arg-type]
        batch_size=batch_size,
        retry_base_delay_seconds=1.0 if clock else 0.01,
        retry_max_delay_seconds=3.0 if clock else 0.05,
        clock=clock or time.monotonic,
    )


async def test_committed_messages_are_published_in_order_and_marked(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    written = await _write(session_factory, "test.command", "test.command", "test.command")

    assert await _relay(session_factory, publisher).relay_batch() == 3

    assert await _drain(queue) == written
    assert await _state(engine) == [(envelope.message_id, True, 1, None) for envelope in written]


async def test_a_published_message_is_not_published_again(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    await _write(session_factory, "test.command")
    relay = _relay(session_factory, publisher)

    assert await relay.relay_batch() == 1
    assert await relay.relay_batch() == 0
    assert len(await _drain(queue)) == 1


async def test_a_batch_takes_at_most_batch_size_rows(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    written = await _write(session_factory, *["test.command"] * 3)
    relay = _relay(session_factory, publisher, batch_size=2)

    assert [await relay.relay_batch() for _ in range(3)] == [2, 1, 0]
    assert await _drain(queue) == written


async def test_a_crash_after_publish_resends_the_message(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """The broker has the message but the row was never marked: the next relay sends it
    again, and the consumer's inbox absorbs the duplicate (test_consumer)."""
    [envelope] = await _write(session_factory, "test.command")

    with pytest.raises(_CrashError):
        await _relay(session_factory, _CrashAfterPublish(publisher)).relay_batch()
    assert await _state(engine) == [(envelope.message_id, False, 0, None)]

    assert await _relay(session_factory, publisher).relay_batch() == 1

    assert await _drain(queue) == [envelope, envelope]
    assert await _state(engine) == [(envelope.message_id, True, 1, None)]


async def test_a_failed_row_does_not_block_the_rows_after_it(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    broker: AbstractRobustConnection,
    broker_settings: BrokerSettings,
    topology: Topology,
    queue: AbstractQueue,
) -> None:
    """No queue accepts ``late.command`` yet (its worker has not declared it). The relay records
    the failure and goes on: the broker carries no job order (the database does), so a row that
    keeps failing must not stall every later command."""
    late, other = await _write(session_factory, "late.command", "test.command")
    clock = _Clock()
    relay = _relay(session_factory, publisher, clock=clock)

    assert await relay.relay_batch() == 1

    failed, published = await _state(engine)
    assert failed[1:3] == (False, 1)
    assert failed[3] is not None and "NO_ROUTE" in failed[3]
    assert published == (other.message_id, True, 1, None)
    assert await _drain(queue) == [other]

    await declare_queue(
        await broker.channel(),
        topology,
        queue_spec(topology, "test.command", "late.command"),
        settings=broker_settings,
    )
    assert await relay.relay_batch() == 0  # still pausing
    clock.now += 1.0
    assert await relay.relay_batch() == 1

    assert await _drain(queue) == [late]
    assert (await _state(engine))[0] == (late.message_id, True, 2, None)


async def test_a_failing_row_waits_a_doubling_pause_up_to_the_maximum(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
) -> None:
    """Pauses of 1 s, 2 s, then 3 s (the maximum): not a retry, an UPDATE and a warning on
    every poll."""
    await _write(session_factory, "nobody.listens")
    clock = _Clock()
    relay = _relay(session_factory, publisher, clock=clock)
    start = clock.now
    attempts = []

    for at in (0, 0.99, 1.0, 2.99, 3.0, 5.99, 6.0):
        clock.now = start + at
        await relay.relay_batch()
        [(_, _, publish_attempts, _)] = await _state(engine)
        attempts.append(publish_attempts)

    assert attempts == [1, 1, 2, 2, 3, 3, 4]


async def test_a_new_relay_retries_a_failed_row_at_once(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
) -> None:
    """The pauses live in the relay process: after a restart the row is tried again."""
    await _write(session_factory, "nobody.listens")
    clock = _Clock()

    await _relay(session_factory, publisher, clock=clock).relay_batch()
    await _relay(session_factory, publisher, clock=clock).relay_batch()

    [(_, _, publish_attempts, _)] = await _state(engine)
    assert publish_attempts == 2


async def test_uncommitted_messages_are_not_published(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await add_outbox_message(uow, message_type="test.command", payload={})

        assert await _relay(session_factory, publisher).relay_batch() == 0

    assert await _drain(queue) == []


async def test_run_publishes_new_messages_until_stopped(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    stop = asyncio.Event()
    running = asyncio.create_task(
        _relay(session_factory, publisher).run(stop, poll_interval_seconds=0.05)
    )

    written = await _write(session_factory, "test.command")
    message = await _wait_for_message(queue)
    stop.set()
    await asyncio.wait_for(running, timeout=5)

    assert Envelope.from_json(message) == written[0]


async def _wait_for_message(queue: AbstractQueue) -> bytes:
    for _ in range(100):
        message = await queue.get(timeout=5, fail=False)
        if message is not None:
            await message.ack()
            return message.body
        await asyncio.sleep(0.05)
    raise AssertionError("the relay did not publish the message")


class _FailsOnce:
    """An unexpected error (not a failed publish) the first time."""

    def __init__(self, publisher: MessagePublisher) -> None:
        self._publisher = publisher
        self.failed = False

    async def publish(self, envelope: Envelope) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("unexpected")
        await self._publisher.publish(envelope)


async def test_run_survives_a_failed_batch(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    queue: AbstractQueue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [envelope] = await _write(session_factory, "test.command")
    failing = _FailsOnce(publisher)
    stop = asyncio.Event()
    running = asyncio.create_task(
        _relay(session_factory, failing).run(stop, poll_interval_seconds=0.05)
    )

    message = await _wait_for_message(queue)
    stop.set()
    await asyncio.wait_for(running, timeout=5)

    assert failing.failed
    assert Envelope.from_json(message) == envelope
    assert await _state(engine) == [(envelope.message_id, True, 2, None)]
    assert "unexpected error publishing outbox row" in caplog.text


async def test_a_row_that_is_not_an_envelope_does_not_undo_the_batch(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """The JSONB column accepts a float the envelope rejects. The rows around it are published
    and marked (else the row before it would be resent on every poll)."""
    [before] = await _write(session_factory, "test.command")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO platform.outbox_messages (message_type, payload)"
                " VALUES ('test.command', '{\"pu\": 1.5}')"
            )
        )
    [after] = await _write(session_factory, "test.command")
    relay = _relay(session_factory, publisher, clock=_Clock())

    assert await relay.relay_batch() == 2
    assert await relay.relay_batch() == 0

    marked, (_, poison_published, attempts, last_error), also_marked = await _state(engine)
    assert marked == (before.message_id, True, 1, None)
    assert (poison_published, attempts) == (False, 1)
    assert last_error is not None and last_error.startswith("not a valid envelope")
    assert "1.5" not in last_error
    assert also_marked == (after.message_id, True, 1, None)
    assert await _drain(queue) == [before, after]


class _ProbesTheLocks:
    """Publishes for real, but first tries to lock the row from another connection, as a
    writer or a second relay would: no relay transaction may hold it while the broker
    answers."""

    def __init__(self, publisher: MessagePublisher, engine: AsyncEngine) -> None:
        self._publisher = publisher
        self._engine = engine
        self.locked: list[bool] = []
        self.open_transactions: list[int] = []

    async def publish(self, envelope: Envelope) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(text("SET LOCAL lock_timeout = '100ms'"))
            locked = await connection.scalar(
                text(
                    "SELECT id FROM platform.outbox_messages"
                    " WHERE message_id = :m FOR UPDATE NOWAIT"
                ),
                {"m": envelope.message_id},
            )
            self.locked.append(locked is not None)
            self.open_transactions.append(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database() AND pid <> pg_backend_pid()"
                        " AND state LIKE 'idle in transaction%'"
                    )
                )
                or 0
            )
        await self._publisher.publish(envelope)


async def test_no_transaction_is_open_while_the_broker_answers(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """The rows are read in one short transaction and marked in another: a broker that takes
    its time to confirm (up to the publish timeout per row) holds no lock and no
    transaction open."""
    written = await _write(session_factory, "test.command", "test.command")
    probing = _ProbesTheLocks(publisher, engine)

    assert await _relay(session_factory, probing).relay_batch() == 2

    assert probing.locked == [True, True]
    assert probing.open_transactions == [0, 0]
    assert await _drain(queue) == written
    assert await _state(engine) == [(envelope.message_id, True, 1, None) for envelope in written]


class _Switch:
    def __init__(self, current: MessagePublisher) -> None:
        self.current = current

    async def publish(self, envelope: Envelope) -> None:
        await self.current.publish(envelope)


async def test_an_unavailable_broker_stops_the_batch_at_its_first_row(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    broker: AbstractRobustConnection,
    broker_settings: BrokerSettings,
    topology: Topology,
    publisher: MessagePublisher,
    queue: AbstractQueue,
) -> None:
    """A closed channel fails every row the same way: the relay records the first row's
    failure and stops, leaving the others untried, and does not pause the row (the broker,
    not the row, failed), so the next poll tries it again."""
    written = await _write(session_factory, *["test.command"] * 3)
    down = await MessagePublisher.create(broker, topology, settings=broker_settings)
    await down.close()
    switch = _Switch(down)
    clock = _Clock()
    relay = _relay(session_factory, switch, clock=clock)

    assert await relay.relay_batch() == 0

    first, *untried = await _state(engine)
    assert first[1:3] == (False, 1)
    assert first[3] is not None
    assert untried == [(envelope.message_id, False, 0, None) for envelope in written[1:]]

    assert await relay.relay_batch() == 0  # clock unchanged: no pause
    assert (await _state(engine))[0][2] == 2

    switch.current = publisher  # the broker is back
    assert await relay.relay_batch() == 3
    assert await _drain(queue) == written


async def test_run_deletes_old_inbox_rows(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
) -> None:
    """The relay's poll loop runs the inbox retention (the worker has no periodic loop: it
    waits for doorbells)."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO platform.inbox_messages (consumer_name, message_id, processed_at)"
                " VALUES ('old', :m, now() - interval '8 days'), ('new', :n, now())"
            ),
            {"m": uuid.uuid4(), "n": uuid.uuid4()},
        )
    retention = InboxRetention(
        unit_of_work_factory(session_factory), older_than=timedelta(days=7), interval_seconds=3600
    )
    stop = asyncio.Event()
    running = asyncio.create_task(
        _relay(session_factory, publisher).run(
            stop, poll_interval_seconds=0.05, retentions=[retention]
        )
    )

    async def consumers() -> list[str]:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT consumer_name FROM platform.inbox_messages")
            )
            return [row[0] for row in rows]

    await eventually(lambda: _only_new(consumers))
    stop.set()
    await asyncio.wait_for(running, timeout=5)


async def _only_new(consumers: Callable[[], Awaitable[list[str]]]) -> bool:
    return await consumers() == ["new"]


async def test_run_deletes_old_published_outbox_rows(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    publisher: MessagePublisher,
) -> None:
    """The outbox otherwise grows by one row per processing request, forever."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO platform.outbox_messages"
                " (message_id, message_type, schema_version, payload, created_at, published_at)"
                " VALUES (:m, 'old', 1, '{}', now() - interval '9 days',"
                " now() - interval '8 days'),"
                " (:n, 'new', 1, '{}', now(), now())"
            ),
            {"m": uuid.uuid4(), "n": uuid.uuid4()},
        )
    retention = OutboxRetention(
        unit_of_work_factory(session_factory), older_than=timedelta(days=7), interval_seconds=3600
    )
    stop = asyncio.Event()
    running = asyncio.create_task(
        _relay(session_factory, publisher).run(
            stop, poll_interval_seconds=0.05, retentions=[retention]
        )
    )

    async def message_types() -> list[str]:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT message_type FROM platform.outbox_messages")
            )
            return [row[0] for row in rows]

    await eventually(lambda: _only_new(message_types))
    stop.set()
    await asyncio.wait_for(running, timeout=5)
