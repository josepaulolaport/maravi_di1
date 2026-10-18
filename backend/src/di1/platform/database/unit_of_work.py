"""The Unit of Work: one `AsyncSession`, one transaction, one commit.

interfaces.md "Transaction boundaries" 1: a write saves the fact and the invalidation of the
dependent results in the same transaction, with one COMMIT. The roles:

- the provider (an HTTP dependency, or a worker's plain factory) opens the UoW with
  ``async with``;
- the service receives it as ``*, uow``, writes through ``uow.session`` (repositories take the
  session from it) and calls ``await uow.commit()`` once;
- leaving the block without a commit, or through an exception, rolls everything back.

A UoW is used once. After the commit its session is no longer handed out: a write there would
start a second transaction that the exit would silently discard.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UnitOfWorkError(RuntimeError):
    """The Unit of Work was used outside its contract (a programming error)."""


class UnitOfWork(Protocol):
    """What a service sees: the transaction's session and the single commit."""

    @property
    def session(self) -> AsyncSession: ...

    async def commit(self) -> None: ...


class _State(enum.Enum):
    NEW = enum.auto()
    ACTIVE = enum.auto()
    COMMITTED = enum.auto()
    CLOSED = enum.auto()


class SqlAlchemyUnitOfWork:
    """`UnitOfWork` over one `AsyncSession` from ``session_factory``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._state = _State.NEW

    async def __aenter__(self) -> Self:
        if self._state is not _State.NEW:
            raise UnitOfWorkError("a unit of work is used once")
        self._session = self._session_factory()
        self._state = _State.ACTIVE
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            return
        try:
            if self._state is _State.ACTIVE:
                await session.rollback()
        finally:
            self._session = None
            self._state = _State.CLOSED
            await session.close()

    @property
    def session(self) -> AsyncSession:
        return self._active_session()

    async def commit(self) -> None:
        session = self._active_session()
        await session.commit()
        self._state = _State.COMMITTED

    def _active_session(self) -> AsyncSession:
        if self._state is _State.COMMITTED:
            raise UnitOfWorkError("the unit of work is already committed")
        if self._state is not _State.ACTIVE or self._session is None:
            raise UnitOfWorkError("the unit of work is not active")
        return self._session


def unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], SqlAlchemyUnitOfWork]:
    """A plain factory of fresh units of work, for workers and dependency providers."""
    return lambda: SqlAlchemyUnitOfWork(session_factory)
