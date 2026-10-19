"""A Unit of Work wraps exactly one `AsyncSession` and one transaction: it commits only when the
service calls `commit()` once, and anything else rolls back.

Sources: interfaces.md "Transaction boundaries" 1 (a write saves the fact in one transaction,
one COMMIT; OQ-31); backend/CLAUDE.md "Services" (a write receives `*, uow` and commits
once); plan §3 (Unit of Work around one AsyncSession). The provider opens the UoW, the service
commits, leaving the block without a commit rolls back (decided with the user, 2026-10-18).

`platform.inbox_messages` is used as a neutral table: no business table is touched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from di1.platform.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
    UnitOfWork,
    UnitOfWorkError,
    unit_of_work_factory,
)

INSERT = text("INSERT INTO platform.inbox_messages (consumer_name, message_id) VALUES (:c, :m)")


class _BoomError(Exception):
    pass


class _TestBase(DeclarativeBase):
    pass


class _InboxRow(_TestBase):
    __tablename__ = "inbox_messages"
    __table_args__ = {"schema": "platform"}  # noqa: RUF012

    consumer_name: Mapped[str] = mapped_column(primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


async def _write(uow: UnitOfWork, message_id: uuid.UUID, consumer: str = "test") -> None:
    await uow.session.execute(INSERT, {"c": consumer, "m": message_id})


async def _stored(engine: AsyncEngine) -> set[uuid.UUID]:
    """What another connection sees: only committed rows."""
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT message_id FROM platform.inbox_messages"))
        return {row[0] for row in rows}


def _checked_out(engine: AsyncEngine) -> int:
    return engine.sync_engine.pool.checkedout()  # type: ignore[attr-defined, no-any-return]


@pytest.fixture
def uow(session_factory: async_sessionmaker[AsyncSession]) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


async def test_commit_makes_the_writes_durable(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    message_id = uuid.uuid4()

    async with uow:
        await _write(uow, message_id)
        await uow.commit()

    assert await _stored(engine) == {message_id}


async def test_leaving_without_commit_rolls_back(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    async with uow:
        await _write(uow, uuid.uuid4())

    assert await _stored(engine) == set()


async def test_an_exception_rolls_back_and_propagates(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    with pytest.raises(_BoomError):
        async with uow:
            await _write(uow, uuid.uuid4())
            raise _BoomError

    assert await _stored(engine) == set()


async def test_writes_are_committed_together_or_not_at_all(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    """A write saves its rows together: when the second fails, the first is not kept."""
    duplicate = uuid.uuid4()

    with pytest.raises(IntegrityError):
        async with uow:
            await _write(uow, uuid.uuid4())
            await _write(uow, duplicate)
            await _write(uow, duplicate)
            await uow.commit()

    assert await _stored(engine) == set()


async def test_a_failed_commit_rolls_back_and_releases_the_connection(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    """The pending ORM row is flushed inside `commit()`, so the commit itself fails."""
    duplicate = uuid.uuid4()

    with pytest.raises(IntegrityError):
        async with uow:
            await _write(uow, uuid.uuid4())
            await _write(uow, duplicate)
            uow.session.add(_InboxRow(consumer_name="test", message_id=duplicate))
            await uow.commit()

    assert await _stored(engine) == set()
    assert _checked_out(engine) == 0


class _RollbackFailedError(Exception):
    pass


async def _failing_rollback() -> None:
    raise _RollbackFailedError


async def test_a_failed_rollback_does_not_mask_the_original_error(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """The caller (problem+json, a job's FAILED status) must see why the block failed."""
    with pytest.raises(_BoomError):
        async with uow:
            await _write(uow, uuid.uuid4())
            uow.session.rollback = _failing_rollback  # type: ignore[method-assign]
            raise _BoomError

    assert await _stored(engine) == set()
    assert _checked_out(engine) == 0
    assert "rollback failed" in caplog.text


async def test_a_failed_rollback_without_another_error_propagates(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    with pytest.raises(_RollbackFailedError):
        async with uow:
            await _write(uow, uuid.uuid4())
            uow.session.rollback = _failing_rollback  # type: ignore[method-assign]

    assert await _stored(engine) == set()
    assert _checked_out(engine) == 0


async def test_an_error_after_commit_keeps_the_committed_writes(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    message_id = uuid.uuid4()

    with pytest.raises(_BoomError):
        async with uow:
            await _write(uow, message_id)
            await uow.commit()
            raise _BoomError

    assert await _stored(engine) == {message_id}


async def test_commit_twice_is_rejected_and_the_first_commit_stands(
    uow: SqlAlchemyUnitOfWork, engine: AsyncEngine
) -> None:
    message_id = uuid.uuid4()

    with pytest.raises(UnitOfWorkError, match="already committed"):
        async with uow:
            await _write(uow, message_id)
            await uow.commit()
            await uow.commit()

    assert await _stored(engine) == {message_id}


async def test_the_session_is_unavailable_after_commit(uow: SqlAlchemyUnitOfWork) -> None:
    """A write after the commit would start a second, silently discarded transaction."""
    async with uow:
        await uow.commit()
        with pytest.raises(UnitOfWorkError, match="already committed"):
            _ = uow.session


async def test_the_session_is_unavailable_outside_the_block(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(UnitOfWorkError, match="not active"):
        _ = uow.session
    with pytest.raises(UnitOfWorkError, match="not active"):
        await uow.commit()

    async with uow:
        pass

    with pytest.raises(UnitOfWorkError, match="not active"):
        _ = uow.session


async def test_a_unit_of_work_is_used_once(uow: SqlAlchemyUnitOfWork) -> None:
    async with uow:
        pass

    with pytest.raises(UnitOfWorkError, match="used once"):
        async with uow:
            pass


async def test_it_cannot_be_entered_while_active(uow: SqlAlchemyUnitOfWork) -> None:
    async with uow:
        with pytest.raises(UnitOfWorkError, match="used once"):
            async with uow:
                pass


async def test_committed_is_true_only_after_a_successful_commit(
    uow: SqlAlchemyUnitOfWork,
) -> None:
    assert not uow.committed
    async with uow:
        assert not uow.committed
        await uow.commit()
        assert uow.committed
    assert not uow.committed


async def test_a_failed_commit_is_not_committed(uow: SqlAlchemyUnitOfWork) -> None:
    duplicate = uuid.uuid4()

    with pytest.raises(IntegrityError):
        async with uow:
            await _write(uow, duplicate)
            uow.session.add(_InboxRow(consumer_name="test", message_id=duplicate))
            try:
                await uow.commit()
            finally:
                assert not uow.committed


async def test_one_session_for_the_whole_block(uow: SqlAlchemyUnitOfWork) -> None:
    async with uow:
        first = uow.session
        await _write(uow, uuid.uuid4())

        assert uow.session is first


async def test_the_connection_is_released_on_every_exit(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    committed = SqlAlchemyUnitOfWork(session_factory)
    async with committed:
        await _write(committed, uuid.uuid4())
        await committed.commit()
    assert _checked_out(engine) == 0

    abandoned = SqlAlchemyUnitOfWork(session_factory)
    async with abandoned:
        await _write(abandoned, uuid.uuid4())
    assert _checked_out(engine) == 0

    failed = SqlAlchemyUnitOfWork(session_factory)
    with pytest.raises(_BoomError):
        async with failed:
            await _write(failed, uuid.uuid4())
            raise _BoomError
    assert _checked_out(engine) == 0


async def test_the_factory_builds_a_new_unit_of_work_each_call(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """Workers use plain factories, not FastAPI `Depends` (interfaces.md "DI composition")."""
    make_uow = unit_of_work_factory(session_factory)
    first_id, second_id = uuid.uuid4(), uuid.uuid4()

    first, second = make_uow(), make_uow()
    assert first is not second
    async with first:
        await _write(first, first_id)
        await first.commit()
    async with second:
        await _write(second, second_id)
        await second.commit()

    assert await _stored(engine) == {first_id, second_id}
