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
    IssueType,
    ProcessingChain,
)
from di1.modules.processing.public import ChainStatus, ProcessingRequest
from di1.platform.database.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class DateStatusRow:
    """One ``processing.date_status`` row with the ``*_previous`` columns (OQ-26): a chain's
    status before it went RUNNING, put back if the run ends without committing the date."""

    day: date
    portfolio: ChainStatus | None = None
    cash: ChainStatus | None = None
    portfolio_previous: ChainStatus | None = None
    cash_previous: ChainStatus | None = None
    portfolio_processed_at: datetime | None = None
    cash_processed_at: datetime | None = None

    def status(self, chain: ProcessingChain) -> ChainStatus | None:
        return self.cash if chain is ProcessingChain.CASH else self.portfolio

    def running(self, chain: ProcessingChain) -> DateStatusRow:
        """``chain`` set RUNNING, keeping its status in ``*_previous``; a chain already RUNNING
        (a recovered date) keeps its ``*_previous`` untouched."""
        if chain is ProcessingChain.CASH:
            if self.cash is ChainStatus.RUNNING:
                return self
            return replace(self, cash=ChainStatus.RUNNING, cash_previous=self.cash)
        if self.portfolio is ChainStatus.RUNNING:
            return self
        return replace(self, portfolio=ChainStatus.RUNNING, portfolio_previous=self.portfolio)

    def settled(
        self, chain: ProcessingChain, status: ChainStatus, processed_at: datetime | None
    ) -> DateStatusRow:
        """``chain`` set to a final status, ``*_previous`` cleared; ``processed_at`` replaces the
        chain's processing time when given (a FAILED date keeps the old one)."""
        if chain is ProcessingChain.CASH:
            return replace(
                self,
                cash=status,
                cash_previous=None,
                cash_processed_at=processed_at or self.cash_processed_at,
            )
        return replace(
            self,
            portfolio=status,
            portfolio_previous=None,
            portfolio_processed_at=processed_at or self.portfolio_processed_at,
        )

    def restored(self) -> DateStatusRow:
        """Every RUNNING chain put back to its ``*_previous`` status (OQ-26)."""
        row = self
        if row.cash is ChainStatus.RUNNING:
            row = replace(row, cash=row.cash_previous, cash_previous=None)
        if row.portfolio is ChainStatus.RUNNING:
            row = replace(row, portfolio=row.portfolio_previous, portfolio_previous=None)
        return row

    @property
    def empty(self) -> bool:
        return self.cash is None and self.portfolio is None


@dataclass(frozen=True, slots=True)
class NewIssue:
    """One Pendência of a date of the positions chain (OQ-31)."""

    issue_type: IssueType
    asset_id: UUID
    affected_date: date
    required_price_date: date | None


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

    async def running_dates(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Sequence[DateStatusRow]:
        """The rows of [start_date, end_date] with a chain RUNNING, row-locked."""
        ...

    async def save_date_status(self, row: DateStatusRow, *, uow: UnitOfWork) -> None:
        """Upserts the row, or deletes it when both chains are without a status (OQ-26)."""
        ...

    async def replace_issues(
        self, request_id: UUID, day: date, issues: Sequence[NewIssue], *, uow: UnitOfWork
    ) -> None:
        """Deletes every issue of ``day`` and writes ``issues`` (OQ-26 item 5)."""
        ...

    def savepoint(self, *, uow: UnitOfWork) -> AbstractAsyncContextManager[object]:
        """A SAVEPOINT in ``uow``'s transaction: leaving it through an exception rolls back to
        it, and the transaction stays usable (OQ-40 item 1)."""
        ...
