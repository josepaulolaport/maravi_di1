"""What Processing's services need from persistence and from the Ledger, as protocols.

The repositories receive the caller's Unit of Work on every call and never commit: the service
owns the transaction (interfaces.md "Transaction boundaries").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from di1.modules.processing.public import ChainStatus, DateStatus, ProcessingRequest
from di1.platform.database.unit_of_work import UnitOfWork


class ProcessingChain(StrEnum):
    """One of the two daily chains (OQ-21)."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"


class IssueType(StrEnum):
    """The two Pendências of spec §10.3 (OQ-19, OQ-31)."""

    MISSING_REFERENCE_PRICE = "MISSING_REFERENCE_PRICE"
    EXPIRED_OPEN_POSITION = "EXPIRED_OPEN_POSITION"


def status_of(status: DateStatus, chain: ProcessingChain) -> ChainStatus | None:
    """The status of ``chain`` on ``status``'s date; ``portfolio`` is the positions chain."""
    return status.cash if chain is ProcessingChain.CASH else status.portfolio


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """One Pendência. ``id`` and ``request_id`` are set once it is stored."""

    issue_type: IssueType
    asset_id: UUID | None
    affected_date: date
    required_price_date: date | None
    id: UUID | None = None
    request_id: UUID | None = None


class DateStatusRepository(Protocol):
    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        """The rows of [start_date, end_date]; a date with no row is absent."""
        ...

    async def has_status_before(
        self, chain: ProcessingChain, day: date, *, uow: UnitOfWork
    ) -> bool:
        """Whether ``chain`` has a status on any date before ``day``."""
        ...


class RequestRepository(Protocol):
    async def add(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None: ...

    async def get(
        self, request_id: UUID, *, uow: UnitOfWork, for_update: bool = False
    ) -> ProcessingRequest | None:
        """The run, row-locked when ``for_update``."""
        ...

    async def get_running(self, *, uow: UnitOfWork) -> ProcessingRequest | None:
        """The run the worker is processing, if any (a plain read, no lock); there is at most one
        (OQ-45)."""
        ...

    async def update(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        """Stores the run's status, timestamps, progress and error."""
        ...

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None, *, uow: UnitOfWork
    ) -> Sequence[ProcessingRequest]:
        """At most ``limit`` runs ordered by ``(created_at, id)`` descending, strictly after the
        keyset ``after`` in that order."""
        ...


class IssueRepository(Protocol):
    async def list_current(self, *, uow: UnitOfWork) -> Sequence[IssueRecord]:
        """Every stored issue, newest affected date first. They are current only because the
        run replaces a chain's issues for a date in that date's transaction (OQ-26 item 5),
        which the Wave 4 worker must do."""
        ...


class ChainHistory(Protocol):
    """The zero state of a chain (OQ-22, OQ-26 item 3), read from the Ledger."""

    async def has_entries_on_or_before(self, chain: ProcessingChain, day: date) -> bool:
        """Positions: a trade dated on or before ``day``; cash: an entry of either type
        (OQ-32: every ledger row is live)."""
        ...
