"""HTTP shapes of Processing: the frontend contract ``frontend/src/api/contract/processing.ts``
(OQ-26 item 8), with OQ-30 and OQ-31 applied (no cancel-and-replace, processed statuses, no
issue chain). Syntax only; the rules are in the service. Every instant is sent in UTC (``Z``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from di1.modules.processing.application.services.processing import (
    IssueView,
    ProcessingPreview,
    RequestPage,
)
from di1.modules.processing.domain.issues import IssueType
from di1.modules.processing.domain.predecessor import PredecessorState
from di1.modules.processing.public import (
    Chain,
    ProcessingErrorCode,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.http import RequestBody, UtcDatetime


class ProcessingRangeRequest(RequestBody):
    """``POST /processing/requests``."""

    start_date: date
    end_date: date
    scope: ProcessingScope


class ProcessingRequestResponse(BaseModel):
    id: UUID
    scope: ProcessingScope
    start_date: date
    end_date: date
    status: ProcessingStatus
    progress_date: date | None
    error_code: ProcessingErrorCode | None
    error_message: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    dispatched_at: UtcDatetime | None
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    cancel_requested_at: UtcDatetime | None
    failed_date: date | None
    """The run's first failure (OQ-40); with ``failed_chain`` it prefills "Solicitar novo
    processamento"."""
    failed_chain: Chain | None
    """CASH or POSITIONS; ``None`` with a ``failed_date`` when the failure belonged to no chain."""

    @classmethod
    def of(cls, request: ProcessingRequest) -> Self:
        return cls(
            id=request.id,
            scope=request.scope,
            start_date=request.start_date,
            end_date=request.end_date,
            status=request.status,
            progress_date=request.progress_date,
            error_code=request.error_code,
            error_message=request.error_message,
            created_at=request.created_at,
            updated_at=request.updated_at,
            dispatched_at=request.dispatched_at,
            started_at=request.started_at,
            finished_at=request.finished_at,
            cancel_requested_at=request.cancel_requested_at,
            failed_date=request.failed_date,
            failed_chain=request.failed_chain,
        )


class ProcessingRequestPageResponse(BaseModel):
    items: list[ProcessingRequestResponse]
    next_cursor: str | None

    @classmethod
    def of(cls, page: RequestPage) -> Self:
        return cls(
            items=[ProcessingRequestResponse.of(item) for item in page.items],
            next_cursor=page.next_cursor,
        )


class PredecessorResponse(BaseModel):
    cash: PredecessorState
    positions: PredecessorState


class ProcessingPreviewResponse(BaseModel):
    start_date: date
    end_date: date
    total_days: int
    scope: ProcessingScope
    predecessor_date: date
    predecessor: PredecessorResponse

    @classmethod
    def of(cls, preview: ProcessingPreview) -> Self:
        return cls(
            start_date=preview.start_date,
            end_date=preview.end_date,
            total_days=preview.total_days,
            scope=preview.scope,
            predecessor_date=preview.predecessor_date,
            predecessor=PredecessorResponse(cash=preview.cash, positions=preview.positions),
        )


class IssueResponse(BaseModel):
    id: UUID
    issue_type: IssueType
    asset_id: UUID | None
    asset_code: str | None
    affected_date: date
    required_price_date: date | None
    request_id: UUID

    @classmethod
    def of(cls, issue: IssueView) -> Self:
        return cls(
            id=issue.id,
            issue_type=issue.issue_type,
            asset_id=issue.asset_id,
            asset_code=issue.asset_code,
            affected_date=issue.affected_date,
            required_price_date=issue.required_price_date,
            request_id=issue.request_id,
        )


class IssueListResponse(BaseModel):
    items: list[IssueResponse]

    @classmethod
    def of(cls, issues: Sequence[IssueView]) -> Self:
        return cls(items=[IssueResponse.of(issue) for issue in issues])
