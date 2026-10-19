"""``/ledger/entries`` (interfaces.md "HTTP endpoints"; OQ-24, OQ-26 item 1): the list of both
entry types, a new entry, and the batch delete. Parse, call `LedgerService`, answer; errors
are `DomainError`s rendered as problem+json by the composition.

The composition builds the router with its providers of the service and of the request's Unit
of Work, so this module imports nothing of the composition.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Response, status

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.domain.listing import ListOrder
from di1.modules.ledger.presentation.http.schemas import (
    CreateLedgerEntryBody,
    DeleteLedgerEntriesBody,
    LedgerEntryPageResponse,
    LedgerEntryResponse,
    entry_response,
)
from di1.platform.database.unit_of_work import UnitOfWork


def create_ledger_router(
    *,
    get_service: Callable[..., LedgerService],
    get_unit_of_work: Callable[..., AsyncIterator[UnitOfWork]],
) -> APIRouter:
    router = APIRouter(prefix="/ledger/entries", tags=["ledger"])
    # Dependency objects built here: the handlers' annotations are strings (PEP 563), resolved
    # from the module's globals, so they cannot name a local alias.
    service_dependency = Depends(get_service)
    uow_dependency = Depends(get_unit_of_work)

    @router.get("", response_model=LedgerEntryPageResponse)
    async def list_entries(
        start_date: date,
        end_date: date,
        search: str | None = None,
        order: ListOrder = ListOrder.DESC,
        limit: int | None = None,
        cursor: str | None = None,
        service: LedgerService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> Any:
        page = await service.list_entries(
            start_date=start_date,
            end_date=end_date,
            search=search,
            order=order,
            limit=limit,
            cursor=cursor,
            uow=uow,
        )
        return LedgerEntryPageResponse(
            items=[entry_response(view) for view in page.items], next_cursor=page.next_cursor
        )

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=LedgerEntryResponse)
    async def create_entry(
        body: CreateLedgerEntryBody,
        service: LedgerService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> Any:
        view = await service.create_entry(body.to_draft(), uow=uow)
        return entry_response(view)

    @router.post("/deletions", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_entries(
        body: DeleteLedgerEntriesBody,
        service: LedgerService = service_dependency,
        uow: UnitOfWork = uow_dependency,
    ) -> Response:
        await service.delete_entries(body.ids, uow=uow)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
