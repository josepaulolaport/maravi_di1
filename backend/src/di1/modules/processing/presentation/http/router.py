"""Processing's HTTP adapter (interfaces.md "HTTP endpoints"; frontend contract
``processing.ts``). Errors are raised by the service as `DomainError` and rendered as
problem+json by the composition, which builds the router with its provider of the service on
the request's Unit of Work (a module cannot import the composition)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, status

from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.presentation.http.schemas import (
    IssueListResponse,
    ProcessingPreviewResponse,
    ProcessingRangeRequest,
    ProcessingRequestPageResponse,
    ProcessingRequestResponse,
)
from di1.modules.processing.public import ProcessingScope
from di1.shared.paging import DEFAULT_LIMIT, PageParams


def create_router(*, get_service: Callable[..., ProcessingService]) -> APIRouter:
    # Dependency objects built here: the handlers' annotations are strings (PEP 563), resolved
    # from the module's globals, so they cannot name a local alias.
    service_dependency = Depends(get_service)
    router = APIRouter(prefix="/processing", tags=["processing"])

    @router.get("/preview")
    async def preview(
        start_date: date,
        end_date: date,
        scope: ProcessingScope,
        service: ProcessingService = service_dependency,
    ) -> ProcessingPreviewResponse:
        return ProcessingPreviewResponse.of(
            await service.preview_range(scope, start_date, end_date)
        )

    @router.get("/requests")
    async def list_requests(
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        service: ProcessingService = service_dependency,
    ) -> ProcessingRequestPageResponse:
        page = await service.list_requests(PageParams(limit=limit, cursor=cursor))
        return ProcessingRequestPageResponse.of(page)

    @router.post("/requests", status_code=status.HTTP_201_CREATED)
    async def enqueue(
        body: ProcessingRangeRequest, service: ProcessingService = service_dependency
    ) -> ProcessingRequestResponse:
        return ProcessingRequestResponse.of(
            await service.enqueue_range(body.scope, body.start_date, body.end_date)
        )

    @router.get("/requests/{request_id}")
    async def get_request(
        request_id: UUID, service: ProcessingService = service_dependency
    ) -> ProcessingRequestResponse:
        return ProcessingRequestResponse.of(await service.get_request(request_id))

    @router.post("/requests/{request_id}/cancel")
    async def cancel(
        request_id: UUID, service: ProcessingService = service_dependency
    ) -> ProcessingRequestResponse:
        return ProcessingRequestResponse.of(await service.request_cancel(request_id))

    @router.get("/issues")
    async def issues(service: ProcessingService = service_dependency) -> IssueListResponse:
        return IssueListResponse.of(await service.get_issues())

    return router
