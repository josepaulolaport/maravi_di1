"""The outbox row is part of the business write's transaction.

interfaces.md "Transaction boundaries" 3 (the dispatch saves its outbox command in the same
transaction); backend/CLAUDE.md "Messaging" (publish only through ``platform.outbox_messages``
and the relay); CLAUDE.md §2 (JSON carries decimal strings).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.platform.messaging.outbox import add_outbox_message


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
