"""Processing's public contract: the request DTO and the per-date chain statuses (interfaces.md
"Processing").

Frozen in W0.3b. Nothing outside Processing writes a status: since OQ-31 a write in Ledger or
Prices saves only the fact, and a date's results change only when the user processes it again.
Changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from di1.platform.database.unit_of_work import UnitOfWork


class ProcessingScope(StrEnum):
    """Which chain a request processes (OQ-21; schema ``requests.scope``). ALL publishes both
    in one transaction."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"
    ALL = "ALL"


class ChainStatus(StrEnum):
    """The current status of one chain on one date (OQ-23, OQ-31; schema
    ``processing.date_status``). A date with no status is "Não processado"."""

    PROCESSED = "PROCESSED"
    """Processado."""
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    """Processado com pendências: a missing price or an expired open position."""
    RUNNING = "RUNNING"
    """Processando."""
    FAILED = "FAILED"
    """Erro: the run failed on this date, e.g. its day before was not processed (OQ-31)."""


@dataclass(frozen=True, slots=True)
class DateStatus:
    """The current status of both chains on one date (OQ-23; ``processing.date_status``);
    ``None`` is "not processed". Each ``*_processed_at`` is when a run last committed that chain
    for the date, shown as "Processado em dd/mm/aaaa hh:mm"; ``None`` if never (OQ-31)."""

    date: date
    portfolio: ChainStatus | None
    cash: ChainStatus | None
    portfolio_processed_at: datetime | None
    cash_processed_at: datetime | None


class DateStatusReader(Protocol):
    """Read access to ``processing.date_status`` for Portfolio's read models (OQ-23)."""

    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        """The statuses of [start_date, end_date], read in ``uow``'s transaction so a caller sees
        them in the same snapshot as its own tables; a date with no row is absent (not
        processed)."""
        ...


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
    ``date_status``. A date whose day before is neither processed nor the chain's zero state
    fails with ``CASH_PREDECESSOR_MISSING`` or ``POSITIONS_PREDECESSOR_MISSING`` (OQ-31). One
    worker processes runs, one at a time, and resumes an interrupted run when it starts (OQ-45)."""

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
    failed_date: date | None
    """The date of the run's first failure (OQ-40); ``None`` if the run never failed."""
    failed_chain: ProcessingScope | None
    """The chain that failed first, ``CASH`` or ``POSITIONS`` (never ``ALL``): the run's chain on a
    single-chain run, ``POSITIONS`` when both fail on the same date (integrator choices). Any
    error raised by a chain's writer call, AUM recompute included, belongs to that chain.
    ``None`` with a ``failed_date`` when the failure belonged to no chain (outside every chain's
    savepoint, e.g. a lock timeout), which fails the date for every chain still alive and the
    run; a worker stopped mid-date is not a failure at D (the run resumes at the worker's start,
    OQ-45).
    Both are kept when the run ends ``CANCELLED``. "Solicitar novo processamento" on
    ``COMPLETED_WITH_ISSUES`` or ``CANCELLED`` also offers this chain's scope from
    ``failed_date`` to ``end_date`` (OQ-40)."""
