"""``/ledger/entries`` (interfaces.md "HTTP endpoints"; OQ-24, OQ-26 item 1): the list of both
entry types, a new entry, and the batch delete. Parse, call `LedgerService`, answer; errors
are `DomainError`s rendered as problem+json by the composition.

The composition builds the router with its provider of the service, so this module imports
nothing of the composition.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, status

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.domain.listing import ListOrder
from di1.modules.ledger.presentation.http.schemas import (
    CreateLedgerEntryRequest,
    DeleteLedgerEntriesRequest,
    LedgerEntryPageResponse,
    LedgerEntryResponse,
    entry_response,
)
from di1.shared.paging import DEFAULT_LIMIT, PageParams


def create_router(*, get_service: Callable[..., LedgerService]) -> APIRouter:
    # Dependency objects built here: the handlers' annotations are strings (PEP 563), resolved
    # from the module's globals, so they cannot name a local alias.
    service_dependency = Depends(get_service)
    router = APIRouter(prefix="/ledger/entries", tags=["ledger"])

    @router.get("")
    async def list_entries(
        start_date: date,
        end_date: date,
        search: str | None = None,
        order: ListOrder = ListOrder.DESC,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        service: LedgerService = service_dependency,
    ) -> LedgerEntryPageResponse:
        page = await service.list_entries(
            start_date=start_date,
            end_date=end_date,
            search=search,
            order=order,
            page=PageParams(limit=limit, cursor=cursor),
        )
        return LedgerEntryPageResponse(
            items=[entry_response(view) for view in page.items], next_cursor=page.next_cursor
        )

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_entry(
        body: CreateLedgerEntryRequest, service: LedgerService = service_dependency
    ) -> LedgerEntryResponse:
        return entry_response(await service.create_entry(body.to_draft()))

    @router.post("/deletions", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_entries(
        body: DeleteLedgerEntriesRequest, service: LedgerService = service_dependency
    ) -> None:
        await service.delete_entries(body.ids)

    return router
