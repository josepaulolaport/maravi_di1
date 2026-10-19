"""`RunStore` on PostgreSQL: rows to records, no business rules. Each call runs in the caller's
Unit of Work and never commits."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Row

from di1.modules.processing.application.interfaces.run_store import (
    DateStatusRow,
    NewIssue,
)
from di1.modules.processing.infrastructure.persistence.errors import is_transient
from di1.modules.processing.infrastructure.persistence.queries import runs as sql
from di1.modules.processing.public import (
    ChainStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock


def _status(value: str | None) -> ChainStatus | None:
    return None if value is None else ChainStatus(value)


def _to_run(row: Row[Any]) -> ProcessingRequest:
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
        error_code=row.error_code,
        error_message=row.error_message,
        updated_at=row.updated_at,
        failed_date=row.failed_date,
        failed_chain=None if row.failed_chain is None else ProcessingScope(row.failed_chain),
    )


def _to_date_status(row: Row[Any]) -> DateStatusRow:
    return DateStatusRow(
        day=row.date,
        portfolio=_status(row.portfolio),
        cash=_status(row.cash),
        portfolio_previous=_status(row.portfolio_previous),
        cash_previous=_status(row.cash_previous),
        portfolio_processed_at=row.portfolio_processed_at,
        cash_processed_at=row.cash_processed_at,
    )


def _value(status: ChainStatus | None) -> str | None:
    return None if status is None else status.value


class SqlRunStore:
    """Satisfies `RunStore`. ``clock`` stamps the ``updated_at``/``created_at`` of the rows it
    writes."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def is_transient(self, error: Exception) -> bool:
        return is_transient(error)

    async def has_queued(self, *, uow: UnitOfWork) -> bool:
        return bool(await uow.session.scalar(sql.EXISTS_QUEUED))

    async def lock_running_runs(self, *, uow: UnitOfWork) -> Sequence[ProcessingRequest]:
        return [_to_run(row) for row in await uow.session.execute(sql.LOCK_RUNNING_RUNS)]

    async def lock_oldest_queued(self, *, uow: UnitOfWork) -> ProcessingRequest | None:
        row = (await uow.session.execute(sql.LOCK_OLDEST_QUEUED)).one_or_none()
        return None if row is None else _to_run(row)

    async def get_run(
        self, request_id: UUID, *, uow: UnitOfWork, for_update: bool = False
    ) -> ProcessingRequest | None:
        result = await uow.session.execute(
            sql.select_run(for_update=for_update), {"id": request_id}
        )
        row = result.one_or_none()
        return None if row is None else _to_run(row)

    async def save_run(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        await uow.session.execute(
            sql.UPDATE_RUN,
            {
                "id": request.id,
                "status": request.status.value,
                "dispatched_at": request.dispatched_at,
                "started_at": request.started_at,
                "finished_at": request.finished_at,
                "cancel_requested_at": request.cancel_requested_at,
                "progress_date": request.progress_date,
                "error_code": request.error_code,
                "error_message": request.error_message,
                "updated_at": request.updated_at,
                "failed_date": request.failed_date,
                "failed_chain": None
                if request.failed_chain is None
                else request.failed_chain.value,
            },
        )

    async def lock_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatusRow]:
        result = await uow.session.execute(
            sql.LOCK_DATE_STATUSES, {"start_date": start_date, "end_date": end_date}
        )
        return {row.date: _to_date_status(row) for row in result}

    async def running_dates(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Sequence[DateStatusRow]:
        result = await uow.session.execute(
            sql.LOCK_RUNNING_DATES, {"start_date": start_date, "end_date": end_date}
        )
        return [_to_date_status(row) for row in result]

    async def save_date_status(self, row: DateStatusRow, *, uow: UnitOfWork) -> None:
        if row.empty:
            await uow.session.execute(sql.DELETE_DATE_STATUS, {"day": row.day})
            return
        await uow.session.execute(
            sql.UPSERT_DATE_STATUS,
            {
                "day": row.day,
                "portfolio": _value(row.portfolio),
                "cash": _value(row.cash),
                "portfolio_previous": _value(row.portfolio_previous),
                "cash_previous": _value(row.cash_previous),
                "portfolio_processed_at": row.portfolio_processed_at,
                "cash_processed_at": row.cash_processed_at,
                "now": self._clock.now(),
            },
        )

    async def replace_issues(
        self, request_id: UUID, day: date, issues: Sequence[NewIssue], *, uow: UnitOfWork
    ) -> None:
        await uow.session.execute(sql.DELETE_ISSUES_OF_DATE, {"day": day})
        if not issues:
            return
        now = self._clock.now()
        await uow.session.execute(
            sql.INSERT_ISSUE,
            [
                {
                    "request_id": request_id,
                    "asset_id": issue.asset_id,
                    "affected_date": issue.affected_date,
                    "required_price_date": issue.required_price_date,
                    "issue_type": issue.issue_type.value,
                    "now": now,
                }
                for issue in issues
            ],
        )

    def savepoint(self, *, uow: UnitOfWork) -> AbstractAsyncContextManager[object]:
        return _savepoint(uow)


@asynccontextmanager
async def _savepoint(uow: UnitOfWork) -> AsyncIterator[object]:
    async with uow.session.begin_nested() as nested:
        yield nested
