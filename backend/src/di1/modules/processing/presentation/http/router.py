"""Processing's HTTP adapter (interfaces.md "HTTP endpoints"; frontend contract
``processing.ts``). Errors are raised by the service as `DomainError` and rendered as
problem+json by the composition."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.presentation.http.schemas import (
    IssueList,
    ProcessingPreviewOut,
    ProcessingRangeBody,
    ProcessingRequestOut,
    ProcessingRequestPage,
)
from di1.modules.processing.public import ProcessingScope
from di1.platform.database.unit_of_work import UnitOfWork

DEFAULT_PAGE_SIZE = 50


def create_router(
    get_service: Callable[..., Any],
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
) -> APIRouter:
    """The routes, with the composition's providers of the service and the request's Unit of
    Work (a module cannot import the composition)."""
    router = APIRouter(prefix="/processing", tags=["processing"])
    service_dependency = Depends(get_service)
    uow_dependency = Depends(get_unit_of_work)

    @router.get("/preview")
    async def preview(
        start_date: date,
        end_date: date,
        scope: ProcessingScope,
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProcessingPreviewOut:
        return ProcessingPreviewOut.of(
            await service.preview_range(scope, start_date, end_date, uow=uow)
        )

    @router.get("/requests")
    async def list_requests(
        limit: int = Query(DEFAULT_PAGE_SIZE),
        cursor: str | None = None,
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProcessingRequestPage:
        return ProcessingRequestPage.of(await service.list_requests(limit, cursor, uow=uow))

    @router.post("/requests", status_code=status.HTTP_201_CREATED)
    async def enqueue(
        body: ProcessingRangeBody,
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProcessingRequestOut:
        return ProcessingRequestOut.of(
            await service.enqueue_range(body.scope, body.start_date, body.end_date, uow=uow)
        )

    @router.get("/requests/{request_id}")
    async def get_request(
        request_id: UUID,
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProcessingRequestOut:
        return ProcessingRequestOut.of(await service.get_request(request_id, uow=uow))

    @router.post("/requests/{request_id}/cancel")
    async def cancel(
        request_id: UUID,
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> ProcessingRequestOut:
        return ProcessingRequestOut.of(await service.request_cancel(request_id, uow=uow))

    @router.get("/issues")
    async def issues(
        service: ProcessingService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> IssueList:
        return IssueList.of(await service.get_issues(uow=uow))

    return router
