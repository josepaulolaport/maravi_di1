"""The inbox records each message once per consumer, in the handler's transaction.

interfaces.md "Transaction boundaries" 7 (at-least-once delivery; inbox idempotency guards
duplicates); backend/CLAUDE.md "Messaging" (handlers idempotent through
``platform.inbox_messages``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from di1.platform.messaging.inbox import InboxRetention, delete_processed_before, record_delivery


async def test_the_first_delivery_is_recorded_and_a_duplicate_is_not(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = uuid.uuid4()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await record_delivery(uow, consumer_name="worker", message_id=message_id)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert not await record_delivery(uow, consumer_name="worker", message_id=message_id)
        await uow.commit()


async def test_each_consumer_records_the_same_message_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = uuid.uuid4()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await record_delivery(uow, consumer_name="a", message_id=message_id)
        assert await record_delivery(uow, consumer_name="b", message_id=message_id)
        assert not await record_delivery(uow, consumer_name="a", message_id=message_id)
        await uow.commit()


async def test_a_rolled_back_delivery_is_not_recorded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A handler that failed must run again on redelivery."""
    message_id = uuid.uuid4()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await record_delivery(uow, consumer_name="worker", message_id=message_id)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await record_delivery(uow, consumer_name="worker", message_id=message_id)
        await uow.commit()


async def test_concurrent_duplicate_deliveries_are_recorded_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two consumers receive the same message at once: the second waits for the first's
    transaction and then sees the duplicate, so exactly one handler runs."""
    message_id = uuid.uuid4()
    first_recorded = asyncio.Event()
    events: list[str] = []

    async def deliver_first() -> bool:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            first = await record_delivery(uow, consumer_name="worker", message_id=message_id)
            first_recorded.set()
            await asyncio.sleep(0.3)  # the second delivery's INSERT starts meanwhile
            events.append("first committing")
            await uow.commit()
            return first

    async def deliver_second() -> bool:
        await first_recorded.wait()
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            events.append("second inserting")
            second = await record_delivery(uow, consumer_name="worker", message_id=message_id)
            events.append("second returned")
            await uow.commit()
            return second

    results = await asyncio.gather(deliver_first(), deliver_second())

    assert list(results) == [True, False]
    # The second INSERT started before the first commit and returned only after it: it waited.
    assert events == ["second inserting", "first committing", "second returned"]


# --- retention (user decision M9, 2026-10-19: keep the inbox, delete old rows) ----------------


async def _record_aged(engine: AsyncEngine, **ages: timedelta) -> None:
    """One inbox row per consumer name, processed ``age`` ago."""
    async with engine.begin() as connection:
        for name, age in ages.items():
            await connection.execute(
                text(
                    "INSERT INTO platform.inbox_messages (consumer_name, message_id, processed_at)"
                    " VALUES (:c, :m, now() - :age)"
                ),
                {"c": name, "m": uuid.uuid4(), "age": age},
            )


async def _consumers(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT consumer_name FROM platform.inbox_messages ORDER BY consumer_name")
        )
        return [row[0] for row in rows]


async def test_rows_processed_before_the_retention_age_are_deleted(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _record_aged(
        engine,
        old=timedelta(days=8),
        edge=timedelta(days=7, minutes=1),
        recent=timedelta(days=6, hours=23),
        new=timedelta(0),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        deleted = await delete_processed_before(uow, older_than=timedelta(days=7))
        await uow.commit()

    assert deleted == 2
    assert await _consumers(engine) == ["new", "recent"]


class _Clock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


async def test_the_retention_runs_at_once_then_once_per_interval(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    clock = _Clock()
    retention = InboxRetention(
        unit_of_work_factory(session_factory),
        older_than=timedelta(days=7),
        interval_seconds=3600,
        clock=clock,
    )
    await _record_aged(engine, first=timedelta(days=8))

    assert await retention.run_if_due() == 1
    await _record_aged(engine, second=timedelta(days=8))
    clock.now += 3599
    assert await retention.run_if_due() is None  # not due yet
    assert await _consumers(engine) == ["second"]
    clock.now += 1
    assert await retention.run_if_due() == 1
    assert await _consumers(engine) == []


async def test_a_failed_retention_is_logged_and_tried_again_at_the_next_interval(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock()
    working = unit_of_work_factory(session_factory)
    calls = 0

    def down_once() -> SqlAlchemyUnitOfWork:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database down")
        return working()

    retention = InboxRetention(
        down_once, older_than=timedelta(days=7), interval_seconds=60, clock=clock
    )

    assert await retention.run_if_due() is None
    assert "inbox retention failed" in caplog.text
    assert await retention.run_if_due() is None  # waits the interval, not every poll
    clock.now += 60
    assert await retention.run_if_due() == 0
