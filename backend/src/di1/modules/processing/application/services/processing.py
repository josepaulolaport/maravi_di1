"""`ProcessingService`: the user's processing requests (spec §10, interfaces.md "Processing").

Enqueueing only records a QUEUED run for exactly [start, end] of one scope (OQ-11, OQ-21);
overlapping and repeated requests are allowed, and the queue is FIFO by ``(created_at, id)``
(OQ-5). Dispatch, the one active run and its execution belong to the worker (Wave 4): nothing
here publishes a message or touches ``processing.calculation_state``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.processing.application.interfaces.repositories import (
    ChainHistory,
    DateStatusRepository,
    IssueRecord,
    IssueRepository,
    IssueType,
    ProcessingChain,
    RequestRepository,
    status_of,
)
from di1.modules.processing.application.services.cursor import decode_cursor, encode_cursor
from di1.modules.processing.public import (
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200
"""The largest page of the run history."""

CANCELLABLE = frozenset(
    {ProcessingStatus.QUEUED, ProcessingStatus.DISPATCHED, ProcessingStatus.RUNNING}
)
"""A run that has not finished and whose cancellation was not already requested."""


class PredecessorState(StrEnum):
    """The day before a range, for one chain (OQ-26 item 8, OQ-31): its status in
    ``date_status``, NOT_PROCESSED without one, or ZERO_STATE when the chain has nothing on or
    before it. Unless it is PROCESSED, PROCESSED_WITH_ISSUES or ZERO_STATE, a run of that chain
    fails on its first date with the chain's ``*_PREDECESSOR_MISSING``."""

    PROCESSED = "PROCESSED"
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    NOT_PROCESSED = "NOT_PROCESSED"
    ZERO_STATE = "ZERO_STATE"


@dataclass(frozen=True, slots=True)
class ProcessingPreview:
    """What a request for exactly [start_date, end_date] would process (OQ-11, OQ-31)."""

    scope: ProcessingScope
    start_date: date
    end_date: date
    total_days: int
    predecessor_date: date
    cash: PredecessorState
    positions: PredecessorState


@dataclass(frozen=True, slots=True)
class RequestPage:
    items: Sequence[ProcessingRequest]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class IssueView:
    """One Pendência with its asset's code (spec §10.3)."""

    id: UUID
    issue_type: IssueType
    asset_id: UUID | None
    asset_code: str | None
    affected_date: date
    required_price_date: date | None
    request_id: UUID


def validate_range(start_date: date, end_date: date, today: date) -> None:
    """``INVALID_RANGE`` when the start is after the end, else ``FUTURE_DATE`` when the range
    ends after today in São Paulo (interfaces.md "Errors", OQ-29)."""
    if start_date > end_date:
        raise DomainError(
            ErrorDetail(
                ErrorCode.INVALID_RANGE,
                "A data inicial deve ser anterior ou igual à data final.",
                "start_date",
            )
        )
    if end_date > today:
        raise DomainError(
            ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "end_date")
        )


def deduplicate(issues: Sequence[IssueRecord]) -> list[IssueRecord]:
    """One issue per obligation (spec §10.3): a missing price per (asset, needed date), an
    expired open position per asset. Each keeps its earliest affected date; the result is
    newest affected date first."""
    kept: dict[tuple[IssueType, UUID | None, date | None], IssueRecord] = {}
    for issue in sorted(issues, key=lambda i: i.affected_date):
        needed = (
            issue.required_price_date
            if issue.issue_type is IssueType.MISSING_REFERENCE_PRICE
            else None
        )
        kept.setdefault((issue.issue_type, issue.asset_id, needed), issue)
    return sorted(kept.values(), key=lambda i: i.affected_date, reverse=True)


def _not_found() -> DomainError:
    return DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Processamento não encontrado."))


def _not_cancellable(status: ProcessingStatus) -> DomainError:
    message = (
        "O cancelamento deste processamento já foi solicitado."
        if status is ProcessingStatus.CANCELLING
        else "Este processamento já foi encerrado e não pode ser cancelado."
    )
    return DomainError(ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, message))


class ProcessingService:
    """Preview, enqueue, cancel and read processing requests and Pendências. Every method takes
    the caller's Unit of Work; the writes commit it once, the reads never do."""

    def __init__(
        self,
        *,
        requests: RequestRepository,
        date_statuses: DateStatusRepository,
        issues: IssueRepository,
        chain_history: ChainHistory,
        assets: AssetReader,
        clock: Clock,
    ) -> None:
        self._requests = requests
        self._date_statuses = date_statuses
        self._issues = issues
        self._chain_history = chain_history
        self._assets = assets
        self._clock = clock

    async def preview_range(
        self, scope: ProcessingScope, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> ProcessingPreview:
        """Exactly [start, end] and, per chain, the state of start−1 (OQ-11, OQ-23, OQ-31).
        Both chains are reported; the scope says which ones the run reads. It only reports a
        missing predecessor: queueing is still allowed, and the run fails on its first date."""
        validate_range(start_date, end_date, self._clock.today())
        predecessor = start_date - timedelta(days=1)
        return ProcessingPreview(
            scope=scope,
            start_date=start_date,
            end_date=end_date,
            total_days=(end_date - start_date).days + 1,
            predecessor_date=predecessor,
            cash=await self._predecessor_state(ProcessingChain.CASH, predecessor, uow),
            positions=await self._predecessor_state(ProcessingChain.POSITIONS, predecessor, uow),
        )

    async def enqueue_range(
        self, scope: ProcessingScope, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> ProcessingRequest:
        """Records a QUEUED run for exactly [start, end] and commits (interfaces.md
        "Transaction boundaries" 2)."""
        validate_range(start_date, end_date, self._clock.today())
        request = await self._add(scope, start_date, end_date, uow)
        await uow.commit()
        logger.info(
            "processing request %s queued: %s %s..%s", request.id, scope, start_date, end_date
        )
        return request

    async def request_cancel(self, request_id: UUID, *, uow: UnitOfWork) -> ProcessingRequest:
        """A queued run is cancelled at once; a dispatched or running one is flagged and the
        worker stops it between dates (spec §10.2)."""
        cancelled = await self._cancel(request_id, uow)
        await uow.commit()
        return cancelled

    async def list_requests(
        self, limit: int, cursor: str | None, *, uow: UnitOfWork
    ) -> RequestPage:
        """Newest first by ``(created_at, id)``, by keyset (OQ-26 item 1)."""
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise DomainError(
                ErrorDetail(
                    ErrorCode.VALIDATION_ERROR,
                    f"Use um limite entre 1 e {MAX_PAGE_SIZE}.",
                    "limit",
                )
            )
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._requests.list_newest_first(limit + 1, after, uow=uow)
        items = rows[:limit]
        next_cursor = (
            encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > limit else None
        )
        return RequestPage(items=items, next_cursor=next_cursor)

    async def get_request(self, request_id: UUID, *, uow: UnitOfWork) -> ProcessingRequest:
        request = await self._requests.get(request_id, uow=uow)
        if request is None:
            raise _not_found()
        return request

    async def get_issues(self, *, uow: UnitOfWork) -> Sequence[IssueView]:
        """The current Pendências, newest affected date first, with their assets' codes."""
        issues = deduplicate(await self._issues.list_current(uow=uow))
        asset_ids = {issue.asset_id for issue in issues if issue.asset_id is not None}
        assets = await self._assets.get_instruments(asset_ids) if asset_ids else {}
        return [
            IssueView(
                id=issue.id,
                issue_type=issue.issue_type,
                asset_id=issue.asset_id,
                asset_code=assets[issue.asset_id].code
                if issue.asset_id is not None and issue.asset_id in assets
                else None,
                affected_date=issue.affected_date,
                required_price_date=issue.required_price_date,
                request_id=issue.request_id,
            )
            for issue in issues
        ]

    async def _predecessor_state(
        self, chain: ProcessingChain, day: date, uow: UnitOfWork
    ) -> PredecessorState:
        """The run's predecessor rule (interfaces.md "Predecessor rule, per day", OQ-37 item 4):
        a status on ``day`` is reported as is; no status while an earlier date of the chain has
        one is a gap, not processed; only when nothing of the chain is processed before is the
        Ledger asked for the zero state."""
        row = (await self._date_statuses.get_date_statuses(day, day, uow=uow)).get(day)
        status = status_of(row, chain) if row is not None else None
        if status is not None:
            return PredecessorState(status)
        if await self._date_statuses.has_status_before(chain, day, uow=uow):
            return PredecessorState.NOT_PROCESSED
        if await self._chain_history.has_entries_on_or_before(chain, day):
            return PredecessorState.NOT_PROCESSED
        return PredecessorState.ZERO_STATE

    async def _add(
        self, scope: ProcessingScope, start_date: date, end_date: date, uow: UnitOfWork
    ) -> ProcessingRequest:
        now = self._clock.now()
        request = ProcessingRequest(
            id=uuid.uuid4(),
            scope=scope,
            start_date=start_date,
            end_date=end_date,
            status=ProcessingStatus.QUEUED,
            created_at=now,
            dispatched_at=None,
            started_at=None,
            finished_at=None,
            cancel_requested_at=None,
            progress_date=None,
            error_code=None,
            error_message=None,
            updated_at=now,
        )
        await self._requests.add(request, uow=uow)
        return request

    async def _cancel(self, request_id: UUID, uow: UnitOfWork) -> ProcessingRequest:
        # The row lock orders this against the dispatcher, the worker and another cancel.
        request = await self._requests.get(request_id, uow=uow, for_update=True)
        if request is None:
            raise _not_found()
        if request.status not in CANCELLABLE:
            raise _not_cancellable(request.status)
        now = self._clock.now()
        if request.status is ProcessingStatus.QUEUED:
            cancelled = replace(
                request,
                status=ProcessingStatus.CANCELLED,
                cancel_requested_at=now,
                finished_at=now,
                updated_at=now,
            )
        else:
            # A dispatched run is flagged like a running one; the worker ends it CANCELLED when
            # it claims it (GAP-G-2, decided by the user).
            cancelled = replace(
                request, status=ProcessingStatus.CANCELLING, cancel_requested_at=now, updated_at=now
            )
        await self._requests.update(cancelled, uow=uow)
        logger.info("processing request %s: cancel requested (%s)", request.id, cancelled.status)
        return cancelled
