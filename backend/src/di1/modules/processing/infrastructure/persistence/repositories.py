"""PostgreSQL repositories of Processing: rows to DTOs, no business rules. Each call runs in the
caller's Unit of Work and never commits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row

from di1.modules.processing.application.interfaces.repositories import (
    IssueRecord,
    IssueType,
    ProcessingChain,
)
from di1.modules.processing.infrastructure.persistence.queries import (
    date_status as date_status_sql,
)
from di1.modules.processing.infrastructure.persistence.queries import issues as issues_sql
from di1.modules.processing.infrastructure.persistence.queries import requests as requests_sql
from di1.modules.processing.public import (
    ChainStatus,
    DateStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import UnitOfWork


def _status(value: str | None) -> ChainStatus | None:
    return None if value is None else ChainStatus(value)


def _to_request(row: Row[Any]) -> ProcessingRequest:
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


def _to_date_status(row: Row[Any]) -> DateStatus:
    return DateStatus(
        date=row.day,
        portfolio=_status(row.portfolio),
        cash=_status(row.cash),
        portfolio_processed_at=row.portfolio_processed_at,
        cash_processed_at=row.cash_processed_at,
    )


class SqlRequestRepository:
    """Satisfies `RequestRepository`."""

    async def add(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        await uow.session.execute(
            requests_sql.insert_request(
                {
                    "id": request.id,
                    "scope": request.scope.value,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    **self._mutable(request),
                    "created_at": request.created_at,
                }
            )
        )

    async def get(
        self, request_id: UUID, *, uow: UnitOfWork, for_update: bool = False
    ) -> ProcessingRequest | None:
        result = await uow.session.execute(
            requests_sql.select_request(request_id, for_update=for_update)
        )
        row = result.one_or_none()
        return None if row is None else _to_request(row)

    async def update(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        await uow.session.execute(requests_sql.update_request(request.id, self._mutable(request)))

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None, *, uow: UnitOfWork
    ) -> Sequence[ProcessingRequest]:
        result = await uow.session.execute(requests_sql.select_newest_first(limit, after))
        return [_to_request(row) for row in result]

    @staticmethod
    def _mutable(request: ProcessingRequest) -> dict[str, Any]:
        return {
            "status": request.status.value,
            "progress_date": request.progress_date,
            "error_code": request.error_code,
            "error_message": request.error_message,
            "updated_at": request.updated_at,
            "dispatched_at": request.dispatched_at,
            "started_at": request.started_at,
            "finished_at": request.finished_at,
            "cancel_requested_at": request.cancel_requested_at,
            "failed_date": request.failed_date,
            "failed_chain": None if request.failed_chain is None else request.failed_chain.value,
        }


class SqlDateStatusRepository:
    """Satisfies `DateStatusRepository` and `public.DateStatusReader`."""

    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        result = await uow.session.execute(date_status_sql.select_range(start_date, end_date))
        return {row.day: _to_date_status(row) for row in result}

    async def has_status_before(
        self, chain: ProcessingChain, day: date, *, uow: UnitOfWork
    ) -> bool:
        column = "cash" if chain is ProcessingChain.CASH else "portfolio"
        found = await uow.session.scalar(date_status_sql.exists_status_before(column, day))
        return bool(found)


class SqlIssueRepository:
    """Satisfies `IssueRepository`."""

    async def list_current(self, *, uow: UnitOfWork) -> Sequence[IssueRecord]:
        result = await uow.session.execute(issues_sql.select_current())
        return [
            IssueRecord(
                id=row.id,
                request_id=row.request_id,
                issue_type=IssueType(row.issue_type),
                asset_id=row.asset_id,
                affected_date=row.affected_date,
                required_price_date=row.required_price_date,
            )
            for row in result
        ]
