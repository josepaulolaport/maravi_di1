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
    """Marks published results stale from a date on; writes only processing metadata."""

    async def trades_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        """A trade dated ``effective_date`` was created or deleted: the cash and the positions
        chains are stale from that date on (OQ-21). Does not commit."""
        ...

    async def cash_movements_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
        """A deposit or withdrawal dated ``effective_date`` was created or deleted: only the
        cash chain is stale from that date on (OQ-21). Does not commit."""
        ...

    async def prices_changed(
        self, asset_id: UUID, reference_date: date, *, uow: UnitOfWork
    ) -> None:
        """A reference price of ``asset_id`` for ``reference_date`` was set, superseded or
        removed: valuation and P&L from that date on are stale. Does not commit."""
        ...


class ProcessingScope(StrEnum):
    """Which chain a request processes (OQ-21; schema ``requests.scope``). ALL publishes both
    in one transaction."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"
    ALL = "ALL"


class ProcessingStatus(StrEnum):
    """The nine job statuses (spec §10.3; schema ``requests_status_check``)."""

    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ISSUES = "COMPLETED_WITH_ISSUES"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    """A user's request to process exactly [start_date, end_date] of one scope (OQ-11, OQ-21;
    schema ``processing.requests``). Claim token, lease and input revisions stay inside
    Processing."""

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
    processed_days: int
    total_days: int | None
    progress_date: date | None
    error_code: str | None
    error_message: str | None
