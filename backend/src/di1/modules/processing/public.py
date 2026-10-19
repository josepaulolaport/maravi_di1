"""Processing's public contract: invalidation of results and the request DTO (interfaces.md
"Processing").

Frozen in W0.3b. Lane G implements `FinancialResultInvalidator`; Ledger and Prices call it in the
same Unit of Work as their write, and it never enqueues processing. Changes go through the
integrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from di1.platform.database.unit_of_work import UnitOfWork


class FinancialResultInvalidator(Protocol):
    """Marks published dates stale from a date on, in ``processing.date_status`` (OQ-23): the
    affected chain becomes STALE on every date >= the given one that has a status."""

    async def trades_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        """A trade dated ``effective_date`` was created or deleted: the cash and the positions
        chains are stale from that date on (OQ-21, OQ-23). Does not commit."""
        ...

    async def cash_movements_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        """A deposit or withdrawal dated ``effective_date`` was created or deleted: only the
        cash chain is stale from that date on (OQ-21, OQ-23). Does not commit."""
        ...

    async def prices_changed(
        self, asset_id: UUID, reference_date: date, *, uow: UnitOfWork
    ) -> None:
        """A reference price of ``asset_id`` for ``reference_date`` was set, corrected or
        removed: the positions chain (valuation and P&L) is stale from that date on (OQ-23,
        OQ-25). Does not commit."""
        ...


class ProcessingScope(StrEnum):
    """Which chain a request processes (OQ-21; schema ``requests.scope``). ALL publishes both
    in one transaction."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"
    ALL = "ALL"


class ChainStatus(StrEnum):
    """The current status of one chain on one date (OQ-23; schema ``processing.date_status``).
    A date with no status is not processed."""

    FRESH = "FRESH"
    FRESH_WITH_ISSUES = "FRESH_WITH_ISSUES"
    STALE = "STALE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


class ProcessingStatus(StrEnum):
    """The eight run statuses (spec §10.3; schema ``requests_status_check``); there is no
    SUPERSEDED since OQ-23."""

    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ISSUES = "COMPLETED_WITH_ISSUES"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    """A run: a user's request to process exactly [start_date, end_date] of one scope, one date
    per transaction (OQ-11, OQ-21, OQ-23; schema ``processing.requests``). ``progress_date`` is
    the last date it committed; the error belongs to the run, the failed date shows FAILED in
    ``date_status``. Claim token and lease stay inside Processing."""

    id: UUID
    scope: ProcessingScope
    start_date: date
    end_date: date
    status: ProcessingStatus
    created_at: datetime
    dispatched_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    progress_date: date | None
    error_code: str | None
    error_message: str | None
    updated_at: datetime
