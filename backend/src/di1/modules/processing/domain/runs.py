"""A processing run: the user's request to process exactly [start_date, end_date] of one scope,
one date per transaction (spec §10; OQ-11, OQ-21, OQ-23, OQ-36, OQ-40, OQ-45, OQ-46; schema
``processing.requests``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from di1.modules.processing.domain.date_status import Chain
from di1.shared.calendar import ONE_DAY
from di1.shared.paging import decode_cursor, encode_cursor


class ProcessingScope(StrEnum):
    """Which chains a run processes (OQ-21; schema ``requests.scope``). ALL writes both chains of
    a date in one transaction, positions first."""

    CASH = "CASH"
    POSITIONS = "POSITIONS"
    ALL = "ALL"

    @property
    def chains(self) -> tuple[Chain, ...]:
        """The chains in the order a date runs them: positions, then cash (integrator choice)."""
        if self is ProcessingScope.ALL:
            return (Chain.POSITIONS, Chain.CASH)
        return (Chain(self.value),)


class ProcessingStatus(StrEnum):
    """The eight run statuses (spec §10.3; schema ``requests_status_check``); there is no
    SUPERSEDED since OQ-23. A request goes QUEUED → RUNNING when the worker takes it, and a cancel
    of a RUNNING run only records ``cancel_requested_at`` (OQ-46). DISPATCHED and CANCELLING stay
    only because the schema's CHECK and the API enum keep them: nothing writes them."""

    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ISSUES = "COMPLETED_WITH_ISSUES"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    @property
    def is_finished(self) -> bool:
        return self in (
            ProcessingStatus.COMPLETED,
            ProcessingStatus.COMPLETED_WITH_ISSUES,
            ProcessingStatus.CANCELLED,
            ProcessingStatus.FAILED,
        )


class ProcessingErrorCode(StrEnum):
    """A run's ``error_code`` (OQ-31, OQ-44); its pt-BR text is the run's ``error_message``."""

    CASH_PREDECESSOR_MISSING = "CASH_PREDECESSOR_MISSING"
    POSITIONS_PREDECESSOR_MISSING = "POSITIONS_PREDECESSOR_MISSING"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    """A technical failure on a date, or of the run itself."""
    SUPERSEDED = "SUPERSEDED"
    """Retired (OQ-23): migration 0003 wrote it on the runs it ended; read, never written."""
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"
    """Retired (OQ-45 reversed OQ-43): runs ended by the recovery cap; read, never written."""

    @classmethod
    def predecessor_missing(cls, chain: Chain) -> ProcessingErrorCode:
        if chain is Chain.CASH:
            return cls.CASH_PREDECESSOR_MISSING
        return cls.POSITIONS_PREDECESSOR_MISSING


PREDECESSOR_MESSAGE = "Dia anterior não processado"
"""The run's message when a date's day before is neither processed nor the zero state (OQ-31)."""
TECHNICAL_ERROR_MESSAGE = "Erro técnico ao processar a data."
"""The run's message for ``PROCESSING_ERROR`` (OQ-44)."""


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    """A run. ``progress_date`` is the last date it committed; the error belongs to the run, the
    failed date shows FAILED in ``date_status``. The run has no lease and no claim token: one
    worker runs it (OQ-45)."""

    id: UUID
    scope: ProcessingScope
    start_date: date
    end_date: date
    status: ProcessingStatus
    created_at: datetime
    dispatched_at: datetime | None
    """Unused since OQ-46 (there is no dispatch); ``None`` for every new run."""
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    """When the user asked to cancel. It stays on record after the run ends; a run that
    completed although a cancel arrived during its last date (OQ-23 item 6) shows only its end
    status: "Cancelando" is shown for a RUNNING run only (OQ-46 item 11, OQ-50 item 6)."""
    progress_date: date | None
    error_code: ProcessingErrorCode | None
    error_message: str | None
    updated_at: datetime
    failed_date: date | None = None
    """The date of the run's first failure (OQ-40); ``None`` if the run never failed."""
    failed_chain: Chain | None = None
    """The chain that failed first: the run's chain on a single-chain run, POSITIONS when both
    fail on the same date (integrator choices). Any error raised by a chain's writer call
    belongs to that chain. ``None`` with a ``failed_date`` when the failure belonged to no chain
    (outside every chain's savepoint, e.g. a lock timeout), which fails the date for every chain
    still alive and the run; a worker crash is not a failure at D (the run recovers when the
    worker starts, OQ-45). Both are kept when the run ends CANCELLED. "Solicitar novo
    processamento" on COMPLETED_WITH_ISSUES or CANCELLED also offers this chain's scope from
    ``failed_date`` to ``end_date`` (OQ-40)."""

    @property
    def next_date(self) -> date:
        """The date the run processes next: the day after ``progress_date``, or the start."""
        return self.start_date if self.progress_date is None else self.progress_date + ONE_DAY

    @property
    def live_chains(self) -> tuple[Chain, ...]:
        """The scope's chains still running: on ALL, the one that failed first has stopped
        (OQ-36). While a run is RUNNING at most one chain has failed: both failing ends it."""
        return tuple(c for c in self.scope.chains if c is not self.failed_chain)

    @property
    def current_date(self) -> date | None:
        """The date a RUNNING run is processing, shown "Processando" (OQ-50 item 4); ``None`` when
        it is not running a date (not RUNNING, or past its end and only recording it)."""
        if self.status is not ProcessingStatus.RUNNING or self.next_date > self.end_date:
            return None
        return self.next_date


@dataclass(frozen=True, slots=True)
class RequestCursor:
    """The keyset of the run history: the ``(created_at, id)`` of a page's last run (spec §12,
    OQ-26 item 1)."""

    created_at: datetime
    id: UUID

    def encode(self) -> str:
        return encode_cursor(self.created_at.isoformat(), str(self.id))

    @classmethod
    def decode(cls, token: str) -> RequestCursor | None:
        """The cursor ``encode`` wrote: an aware ISO instant and a UUID; ``None`` otherwise."""
        parts = decode_cursor(token, parts=2)
        if parts is None:
            return None
        try:
            cursor = cls(datetime.fromisoformat(parts[0]), UUID(parts[1]))
        except ValueError:
            return None
        return cursor if cursor.created_at.tzinfo is not None else None
