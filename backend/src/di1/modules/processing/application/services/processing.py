"""`ProcessingService`: the user's processing requests (spec §10, interfaces.md "Processing").

Enqueueing records a QUEUED run for exactly [start, end] of one scope (OQ-11, OQ-21) and writes
its run message in the same transaction; overlapping and repeated requests are allowed, and the
worker runs them one at a time, its sweep taking them FIFO by ``(created_at, id)`` (OQ-5).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.processing.application.ports import (
    ChainHistory,
    DateStatusRepository,
    IssueRepository,
    RequestRepository,
    RunMessages,
)
from di1.modules.processing.application.services.predecessor import read_predecessor
from di1.modules.processing.domain.date_status import Chain
from di1.modules.processing.domain.issues import IssueType, deduplicate
from di1.modules.processing.domain.predecessor import PredecessorState
from di1.modules.processing.domain.runs import (
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
    RequestCursor,
)
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.calendar import ONE_DAY
from di1.shared.clock import Clock
from di1.shared.errors import (
    DomainError,
    ErrorCode,
    ErrorDetail,
    future_date,
    invalid_cursor,
    invalid_range,
    range_too_long,
)
from di1.shared.paging import PageParams

logger = logging.getLogger(__name__)


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
    """``INVALID_RANGE`` when the start is the first representable date (it has no day before)
    or after the end, or when the range holds more than ``MAX_RANGE_DATES`` dates; else
    ``FUTURE_DATE`` when the range ends after today in São Paulo (interfaces.md "Errors",
    OQ-29)."""
    if start_date == date.min:
        # The run and the preview need the day before the start; 01/01/0001 has none.
        raise DomainError(
            ErrorDetail(
                ErrorCode.INVALID_RANGE,
                "A data inicial deve ser posterior a 01/01/0001.",
                "start_date",
            )
        )
    if start_date > end_date:
        raise DomainError(invalid_range())
    if (too_long := range_too_long(start_date, end_date)) is not None:
        raise DomainError(too_long)
    if end_date > today:
        raise DomainError(future_date("end_date"))


def _not_found() -> DomainError:
    return DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Processamento não encontrado."))


def _not_cancellable(request: ProcessingRequest) -> DomainError:
    """An ended run answers "encerrado", whatever cancel it has on record; "já foi solicitado"
    only for a RUNNING run whose cancel is pending (OQ-46)."""
    pending = request.status is ProcessingStatus.RUNNING and request.cancel_requested_at is not None
    message = (
        "O cancelamento deste processamento já foi solicitado."
        if pending
        else "Este processamento já foi encerrado e não pode ser cancelado."
    )
    return DomainError(ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, message))


class ProcessingService:
    """Preview, enqueue, cancel and read processing requests and Pendências, on one Unit of Work:
    the writes commit it once, the reads never do."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        requests: RequestRepository,
        date_statuses: DateStatusRepository,
        issues: IssueRepository,
        chain_history: ChainHistory,
        run_messages: RunMessages,
        assets: AssetReader,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._requests = requests
        self._date_statuses = date_statuses
        self._issues = issues
        self._chain_history = chain_history
        self._run_messages = run_messages
        self._assets = assets
        self._clock = clock

    async def preview_range(
        self, scope: ProcessingScope, start_date: date, end_date: date
    ) -> ProcessingPreview:
        """Exactly [start, end] and, per chain, the state of start−1 (OQ-11, OQ-23, OQ-31).
        Both chains are reported; the scope says which ones the run reads. It only reports a
        missing predecessor: queueing is still allowed, and the run fails on its first date."""
        validate_range(start_date, end_date, self._clock.today())
        predecessor = start_date - ONE_DAY
        return ProcessingPreview(
            scope=scope,
            start_date=start_date,
            end_date=end_date,
            total_days=(end_date - start_date).days + 1,
            predecessor_date=predecessor,
            cash=await self._predecessor_state(Chain.CASH, predecessor),
            positions=await self._predecessor_state(Chain.POSITIONS, predecessor),
        )

    async def enqueue_range(
        self, scope: ProcessingScope, start_date: date, end_date: date
    ) -> ProcessingRequest:
        """Records a QUEUED run for exactly [start, end], writes its run message in the same
        transaction, and commits (interfaces.md "Transaction boundaries" 2)."""
        validate_range(start_date, end_date, self._clock.today())
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
        await self._requests.add(request)
        await self._run_messages.publish(request.id)
        await self._uow.commit()
        logger.info(
            "processing request %s queued: %s %s..%s", request.id, scope, start_date, end_date
        )
        return request

    async def request_cancel(self, request_id: UUID) -> ProcessingRequest:
        """A queued run is cancelled at once; a running one gets ``cancel_requested_at`` and the
        worker stops it between dates (spec §10.2, OQ-46). A second cancel, or one of an ended
        run, answers JOB_NOT_CANCELLABLE."""
        # The row lock orders this against the worker and another cancel.
        request = await self._requests.get(request_id, for_update=True)
        if request is None:
            raise _not_found()
        cancellable = request.status in (ProcessingStatus.QUEUED, ProcessingStatus.RUNNING)
        if not cancellable or request.cancel_requested_at is not None:
            raise _not_cancellable(request)
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
            # A running run keeps RUNNING; the worker sees the flag between dates (OQ-46).
            cancelled = replace(request, cancel_requested_at=now, updated_at=now)
        await self._requests.save(cancelled)
        await self._uow.commit()
        logger.info("processing request %s: cancel requested (%s)", request.id, cancelled.status)
        return cancelled

    async def list_requests(self, page: PageParams) -> RequestPage:
        """Newest first by ``(created_at, id)``, by keyset (OQ-26 item 1)."""
        if errors := page.errors():
            raise DomainError(*errors)
        # The cursor is checked only once the page size is valid.
        after = None if page.cursor is None else RequestCursor.decode(page.cursor)
        if page.cursor is not None and after is None:
            raise DomainError(invalid_cursor())
        keyset = None if after is None else (after.created_at, after.id)
        rows = await self._requests.list_newest_first(page.limit + 1, keyset)
        items = rows[: page.limit]
        next_cursor = (
            RequestCursor(items[-1].created_at, items[-1].id).encode()
            if len(rows) > page.limit
            else None
        )
        return RequestPage(items=items, next_cursor=next_cursor)

    async def get_request(self, request_id: UUID) -> ProcessingRequest:
        request = await self._requests.get(request_id)
        if request is None:
            raise _not_found()
        return request

    async def get_issues(self) -> Sequence[IssueView]:
        """The current Pendências, newest affected date first, with their assets' codes."""
        issues = deduplicate(await self._issues.list_current())
        asset_ids = {issue.asset_id for issue in issues if issue.asset_id is not None}
        assets = await self._assets.get_instruments(asset_ids) if asset_ids else {}
        views: list[IssueView] = []
        for issue in issues:
            if issue.id is None or issue.request_id is None:
                raise RuntimeError("a stored Pendência has an id")
            asset = None if issue.asset_id is None else assets.get(issue.asset_id)
            views.append(
                IssueView(
                    id=issue.id,
                    issue_type=issue.issue_type,
                    asset_id=issue.asset_id,
                    asset_code=None if asset is None else asset.code,
                    affected_date=issue.affected_date,
                    required_price_date=issue.required_price_date,
                    request_id=issue.request_id,
                )
            )
        return views

    async def _predecessor_state(self, chain: Chain, day: date) -> PredecessorState:
        """The run's predecessor rule on ``day``: the state the run's first date would find."""
        stored = (await self._date_statuses.get_range(day, day)).get(day)
        return await read_predecessor(
            chain,
            day,
            None if stored is None else stored.status(chain),
            date_statuses=self._date_statuses,
            history=self._chain_history,
        )
