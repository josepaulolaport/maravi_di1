"""HTTP shapes of Processing: the frontend contract ``frontend/src/api/contract/processing.ts``
(OQ-26 item 8), with OQ-30 and OQ-31 applied (no cancel-and-replace, processed statuses, no
issue chain). Syntax only; the rules are in the
service."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel

from di1.modules.processing.application.interfaces.repositories import (
    IssueType,
    ProcessingChain,
)
from di1.modules.processing.application.services.processing import (
    IssueView,
    PredecessorState,
    ProcessingPreview,
    RequestPage,
)
from di1.modules.processing.public import ProcessingRequest, ProcessingScope, ProcessingStatus


class ProcessingRangeBody(BaseModel):
    """``POST /processing/requests``."""

    start_date: date
    end_date: date
    scope: ProcessingScope


def _utc(moment: datetime | None) -> datetime | None:
    """One rendering for every run timestamp: the service stamps runs in São Paulo time and
    PostgreSQL reads them back in UTC, so both are sent in UTC (``Z``)."""
    return None if moment is None else moment.astimezone(UTC)


class ProcessingRequestOut(BaseModel):
    id: UUID
    scope: ProcessingScope
    start_date: date
    end_date: date
    status: ProcessingStatus
    progress_date: date | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    failed_date: date | None
    """The run's first failure (OQ-40); with ``failed_chain`` it prefills "Solicitar novo
    processamento"."""
    failed_chain: ProcessingChain | None
    """CASH or POSITIONS; ``None`` with a ``failed_date`` when the failure belonged to no chain."""

    @classmethod
    def of(cls, request: ProcessingRequest) -> ProcessingRequestOut:
        return cls(
            id=request.id,
            scope=request.scope,
            start_date=request.start_date,
            end_date=request.end_date,
            status=request.status,
            progress_date=request.progress_date,
            error_code=request.error_code,
            error_message=request.error_message,
            created_at=request.created_at.astimezone(UTC),
            updated_at=request.updated_at.astimezone(UTC),
            dispatched_at=_utc(request.dispatched_at),
            started_at=_utc(request.started_at),
            finished_at=_utc(request.finished_at),
            cancel_requested_at=_utc(request.cancel_requested_at),
            failed_date=request.failed_date,
            failed_chain=None
            if request.failed_chain is None
            else ProcessingChain(request.failed_chain.value),
        )


class ProcessingRequestPage(BaseModel):
    items: list[ProcessingRequestOut]
    next_cursor: str | None

    @classmethod
    def of(cls, page: RequestPage) -> ProcessingRequestPage:
        return cls(
            items=[ProcessingRequestOut.of(item) for item in page.items],
            next_cursor=page.next_cursor,
        )


class PredecessorOut(BaseModel):
    cash: PredecessorState
    positions: PredecessorState


class ProcessingPreviewOut(BaseModel):
    start_date: date
    end_date: date
    total_days: int
    scope: ProcessingScope
    predecessor_date: date
    predecessor: PredecessorOut

    @classmethod
    def of(cls, preview: ProcessingPreview) -> ProcessingPreviewOut:
        return cls(
            start_date=preview.start_date,
            end_date=preview.end_date,
            total_days=preview.total_days,
            scope=preview.scope,
            predecessor_date=preview.predecessor_date,
            predecessor=PredecessorOut(cash=preview.cash, positions=preview.positions),
        )


class IssueOut(BaseModel):
    id: UUID
    issue_type: IssueType
    asset_id: UUID | None
    asset_code: str | None
    affected_date: date
    required_price_date: date | None
    request_id: UUID

    @classmethod
    def of(cls, issue: IssueView) -> IssueOut:
        return cls(
            id=issue.id,
            issue_type=issue.issue_type,
            asset_id=issue.asset_id,
            asset_code=issue.asset_code,
            affected_date=issue.affected_date,
            required_price_date=issue.required_price_date,
            request_id=issue.request_id,
        )


class IssueList(BaseModel):
    items: list[IssueOut]

    @classmethod
    def of(cls, issues: Sequence[IssueView]) -> IssueList:
        return cls(items=[IssueOut.of(issue) for issue in issues])
