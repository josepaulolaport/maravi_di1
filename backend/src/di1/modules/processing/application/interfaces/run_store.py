"""What the worker needs from persistence (interfaces.md "Processing", "Transaction boundaries"
4 and 6; OQ-46).

Every call runs in the caller's Unit of Work and never commits: the processor owns its
transactions, one per step (take, RUNNING, the date, the end).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from di1.modules.processing.application.interfaces.repositories import (
    IssueRecord,
    ProcessingChain,
)
from di1.modules.processing.public import ChainStatus, ProcessingRequest
from di1.platform.database.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class DateStatusRow:
    """One ``processing.date_status`` row. A date goes from its old status straight to its new
    one in its own transaction; no ``RUNNING`` is stored and the ``*_previous`` columns are unused
    (OQ-50 item 4)."""

    day: date
    portfolio: ChainStatus | None = None
    cash: ChainStatus | None = None
    portfolio_processed_at: datetime | None = None
    cash_processed_at: datetime | None = None

    def status(self, chain: ProcessingChain) -> ChainStatus | None:
        return self.cash if chain is ProcessingChain.CASH else self.portfolio

    def settled(
        self, chain: ProcessingChain, status: ChainStatus, processed_at: datetime | None
    ) -> DateStatusRow:
        """``chain`` set to its new status; ``processed_at`` replaces the chain's processing time
        when given (a FAILED date keeps the old one)."""
        if chain is ProcessingChain.CASH:
            return replace(
                self, cash=status, cash_processed_at=processed_at or self.cash_processed_at
            )
        return replace(
            self,
            portfolio=status,
            portfolio_processed_at=processed_at or self.portfolio_processed_at,
        )


class RunStore(Protocol):
    def is_transient(self, error: Exception) -> bool:
        """Whether ``error``, raised by a call of this store or by its Unit of Work, may clear on
        a retry or a restart (a dropped connection, a timeout); any other fails the same way on
        every try."""
        ...

    async def lock_oldest_queued(self, *, uow: UnitOfWork) -> ProcessingRequest | None:
        """The oldest QUEUED run by ``(created_at, id)``, row-locked (OQ-5 item 4, OQ-46)."""
        ...

    async def has_queued(self, *, uow: UnitOfWork) -> bool:
        """Whether any run is QUEUED (a plain read)."""
        ...

    async def lock_the_queue(self, *, uow: UnitOfWork) -> None:
        """Takes the queue's transaction-scoped lock, held until the Unit of Work ends: two takes
        are serialized, so "nothing RUNNING, then lock the oldest QUEUED" is one atomic step."""
        ...

    async def lock_running_runs(self, *, uow: UnitOfWork) -> Sequence[ProcessingRequest]:
        """The RUNNING runs, oldest first, row-locked: the run the worker is processing, or at
        its start the one it was (OQ-45). DISPATCHED and CANCELLING are never written (OQ-46)."""
        ...

    async def get_run(
        self, request_id: UUID, *, uow: UnitOfWork, for_update: bool = False
    ) -> ProcessingRequest | None: ...

    async def save_run(self, run: ProcessingRequest, *, uow: UnitOfWork) -> None:
        """Stores every mutable column of the run, its failure included."""
        ...

    async def lock_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatusRow]:
        """The rows of [start_date, end_date], row-locked in ascending date order; a date with
        no row is absent."""
        ...

    async def save_date_status(self, row: DateStatusRow, *, uow: UnitOfWork) -> None:
        """Upserts the row's statuses and processing times."""
        ...

    async def replace_issues(
        self, request_id: UUID, day: date, issues: Sequence[IssueRecord], *, uow: UnitOfWork
    ) -> None:
        """Deletes every issue of ``day`` and writes ``issues`` (OQ-26 item 5)."""
        ...

    def savepoint(self, *, uow: UnitOfWork) -> AbstractAsyncContextManager[object]:
        """A SAVEPOINT in ``uow``'s transaction: leaving it through an exception rolls back to
        it, and the transaction stays usable (OQ-40 item 1)."""
        ...
