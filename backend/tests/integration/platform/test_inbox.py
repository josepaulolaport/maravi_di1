"""The inbox records each message once per consumer, in the handler's transaction.

interfaces.md "Transaction boundaries" 7 (at-least-once delivery; inbox idempotency guards
duplicates); backend/CLAUDE.md "Messaging" (handlers idempotent through
``platform.inbox_messages``).
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.inbox import record_delivery


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
