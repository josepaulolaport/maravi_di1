"""The outbox row is part of the business write's transaction.

Processing's run message is saved in the same transaction as the request it names;
backend/CLAUDE.md "Messaging" (publish only through ``platform.outbox_messages`` and the
relay); CLAUDE.md §2 (JSON carries decimal strings).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from di1.platform.messaging.outbox import (
    OutboxRetention,
    add_outbox_message,
    delete_published_before,
)


class _BoomError(Exception):
    pass


async def _outbox_rows(engine: AsyncEngine) -> list[tuple[object, ...]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT message_id, message_type, schema_version, payload, published_at,"
                " publish_attempts, last_error, created_at FROM platform.outbox_messages"
                " ORDER BY id"
            )
        )
        return [tuple(row) for row in rows]


async def test_the_outbox_message_is_stored_on_commit(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        envelope = await add_outbox_message(
            uow, message_type="test.command", payload={"id": "42", "values": [1, "2.50"]}
        )
        await uow.commit()

    [row] = await _outbox_rows(engine)
    assert row[:7] == (
        envelope.message_id,
        "test.command",
        1,
        {"id": "42", "values": [1, "2.50"]},
        None,
        0,
        None,
    )
    assert row[7] == envelope.created_at


async def test_the_outbox_message_rolls_back_with_the_business_write(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    with pytest.raises(_BoomError):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await add_outbox_message(uow, message_type="test.command", payload={})
            raise _BoomError

    assert await _outbox_rows(engine) == []


async def test_each_outbox_message_gets_its_own_id_and_version(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first = await add_outbox_message(uow, message_type="a", payload={})
        second = await add_outbox_message(uow, message_type="b", payload={}, schema_version=2)
        await uow.commit()

    assert first.message_id != second.message_id
    assert [(row[0], row[2]) for row in await _outbox_rows(engine)] == [
        (first.message_id, 1),
        (second.message_id, 2),
    ]


async def test_an_invalid_outbox_message_is_rejected_before_writing(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError, match="float"):
            await add_outbox_message(uow, message_type="test.command", payload={"pu": 1.5})
        await uow.commit()

    assert await _outbox_rows(engine) == []


async def _add_aged(engine: AsyncEngine, **published_ago: timedelta | None) -> None:
    """One outbox row per name (its ``message_type``), published that long ago (``None``: not
    published yet, though created long ago)."""
    async with engine.begin() as connection:
        for name, age in published_ago.items():
            await connection.execute(
                text(
                    "INSERT INTO platform.outbox_messages"
                    " (message_id, message_type, schema_version, payload, created_at, published_at)"
                    " VALUES (gen_random_uuid(), :name, 1, '{}', now() - interval '30 days',"
                    " now() - CAST(:age AS interval))"
                ),
                {"name": name, "age": age},
            )


async def _message_types(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT message_type FROM platform.outbox_messages ORDER BY message_type")
        )
        return [row[0] for row in rows]


async def test_rows_published_before_the_retention_age_are_deleted(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """A published row is only history; an unpublished one, however old, must still be sent."""
    await _add_aged(
        engine,
        old=timedelta(days=8),
        edge=timedelta(days=7, minutes=1),
        recent=timedelta(days=6, hours=23),
        new=timedelta(0),
        unpublished=None,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        deleted = await delete_published_before(uow, older_than=timedelta(days=7))
        await uow.commit()

    assert deleted == 2
    assert await _message_types(engine) == ["new", "recent", "unpublished"]


async def test_the_outbox_retention_runs_at_once_then_once_per_interval(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    now = [500.0]
    retention = OutboxRetention(
        unit_of_work_factory(session_factory),
        older_than=timedelta(days=7),
        interval_seconds=3600,
        clock=lambda: now[0],
    )
    await _add_aged(engine, first=timedelta(days=8))

    assert await retention.run_if_due() == 1
    await _add_aged(engine, second=timedelta(days=8))
    now[0] += 3599
    assert await retention.run_if_due() is None  # not due yet
    now[0] += 1
    assert await retention.run_if_due() == 1
    assert await _message_types(engine) == []
