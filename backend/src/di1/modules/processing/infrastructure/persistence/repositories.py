"""Processing's PostgreSQL repositories, one per table, each on one session: rows in, records
out, no business rule. None of them commits."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.processing.domain.date_status import Chain, ChainStatus, DateStatus
from di1.modules.processing.domain.issues import IssueRecord, IssueType
from di1.modules.processing.domain.runs import (
    ProcessingErrorCode,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.modules.processing.infrastructure.persistence.models import (
    DateStatusRow,
    IssueRow,
    RequestRow,
)
from di1.modules.processing.infrastructure.persistence.queries import date_status as status_sql
from di1.modules.processing.infrastructure.persistence.queries import issues as issues_sql
from di1.modules.processing.infrastructure.persistence.queries import requests as requests_sql
from di1.shared.clock import Clock


class SqlRequestRepository:
    """Implements `RequestRepository` on one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: ProcessingRequest) -> None:
        await self._session.execute(
            requests_sql.insert_request(
                {
                    "id": request.id,
                    "scope": request.scope.value,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "created_at": request.created_at,
                    **_mutable(request),
                }
            )
        )

    async def get(self, request_id: UUID, *, for_update: bool = False) -> ProcessingRequest | None:
        row = await self._session.scalar(requests_sql.request(request_id, for_update=for_update))
        return None if row is None else _to_request(row)

    async def save(self, request: ProcessingRequest) -> None:
        await self._session.execute(requests_sql.update_request(request.id, _mutable(request)))

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None
    ) -> Sequence[ProcessingRequest]:
        rows = await self._session.scalars(requests_sql.newest_first(limit, after))
        return [_to_request(row) for row in rows]

    async def get_running(self) -> ProcessingRequest | None:
        rows = await self._session.scalars(requests_sql.running(for_update=False).limit(1))
        row = rows.first()
        return None if row is None else _to_request(row)

    async def lock_queue(self) -> None:
        await self._session.execute(requests_sql.LOCK_QUEUE, {"key": requests_sql.QUEUE_LOCK_KEY})

    async def lock_running(self) -> Sequence[ProcessingRequest]:
        rows = await self._session.scalars(requests_sql.running(for_update=True))
        return [_to_request(row) for row in rows]

    async def lock_oldest_queued(self) -> ProcessingRequest | None:
        row = await self._session.scalar(requests_sql.oldest_queued())
        return None if row is None else _to_request(row)

    async def has_queued(self) -> bool:
        return bool(await self._session.scalar(requests_sql.any_queued()))


class SqlDateStatusRepository:
    """Implements `DateStatusRepository` on one session: the statuses as stored. ``clock``
    stamps ``updated_at``, like every processing timestamp."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def get_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        return await self._range(start_date, end_date, for_update=False)

    async def lock_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        return await self._range(start_date, end_date, for_update=True)

    async def has_status_before(self, chain: Chain, day: date) -> bool:
        return bool(await self._session.scalar(status_sql.any_status_before(chain, day)))

    async def save(self, status: DateStatus) -> None:
        await self._session.execute(
            status_sql.upsert(
                status.date,
                {
                    "portfolio": _value(status.portfolio),
                    "cash": _value(status.cash),
                    "portfolio_processed_at": status.portfolio_processed_at,
                    "cash_processed_at": status.cash_processed_at,
                },
                self._clock.now(),
            )
        )

    async def _range(
        self, start_date: date, end_date: date, *, for_update: bool
    ) -> Mapping[date, DateStatus]:
        rows = await self._session.scalars(
            status_sql.date_range(start_date, end_date, for_update=for_update)
        )
        return {row.day: _to_date_status(row) for row in rows}


class SqlIssueRepository:
    """Implements `IssueRepository` on one session; ``clock`` stamps ``created_at``."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def list_current(self) -> Sequence[IssueRecord]:
        return [_to_issue(row) for row in await self._session.scalars(issues_sql.current())]

    async def replace_for_date(
        self, request_id: UUID, day: date, issues: Sequence[IssueRecord]
    ) -> None:
        await self._session.execute(issues_sql.delete_of_date(day))
        if not issues:
            return
        now = self._clock.now()
        await self._session.execute(
            issues_sql.insert_issues(
                [
                    {
                        "request_id": request_id,
                        "asset_id": issue.asset_id,
                        "affected_date": issue.affected_date,
                        "required_price_date": issue.required_price_date,
                        "issue_type": issue.issue_type.value,
                        "created_at": now,
                    }
                    for issue in issues
                ]
            )
        )


@asynccontextmanager
async def savepoint(session: AsyncSession) -> AsyncIterator[object]:
    """A SAVEPOINT on ``session``: leaving it through an exception rolls back to it."""
    async with session.begin_nested() as nested:
        yield nested


def _mutable(request: ProcessingRequest) -> dict[str, Any]:
    return {
        "status": request.status.value,
        "progress_date": request.progress_date,
        "error_code": _value(request.error_code),
        "error_message": request.error_message,
        "updated_at": request.updated_at,
        "dispatched_at": request.dispatched_at,
        "started_at": request.started_at,
        "finished_at": request.finished_at,
        "cancel_requested_at": request.cancel_requested_at,
        "failed_date": request.failed_date,
        "failed_chain": _value(request.failed_chain),
    }


def _value(member: ChainStatus | Chain | ProcessingErrorCode | None) -> str | None:
    return None if member is None else member.value


def _to_request(row: RequestRow) -> ProcessingRequest:
    return ProcessingRequest(
        id=row.id,
        scope=ProcessingScope(row.scope),
        start_date=row.start_date,
        end_date=row.end_date,
        status=ProcessingStatus(row.status),
        created_at=row.created_at,
        dispatched_at=row.dispatched_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cancel_requested_at=row.cancel_requested_at,
        progress_date=row.progress_date,
        error_code=None if row.error_code is None else ProcessingErrorCode(row.error_code),
        error_message=row.error_message,
        updated_at=row.updated_at,
        failed_date=row.failed_date,
        failed_chain=None if row.failed_chain is None else Chain(row.failed_chain),
    )


def _to_date_status(row: DateStatusRow) -> DateStatus:
    return DateStatus(
        date=row.day,
        portfolio=None if row.portfolio is None else ChainStatus(row.portfolio),
        cash=None if row.cash is None else ChainStatus(row.cash),
        portfolio_processed_at=row.portfolio_processed_at,
        cash_processed_at=row.cash_processed_at,
    )


def _to_issue(row: IssueRow) -> IssueRecord:
    return IssueRecord(
        id=row.id,
        request_id=row.request_id,
        issue_type=IssueType(row.issue_type),
        asset_id=row.asset_id,
        affected_date=row.affected_date,
        required_price_date=row.required_price_date,
    )
