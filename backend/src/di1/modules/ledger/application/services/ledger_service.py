"""Ledger's writes and its list read (interfaces.md "Ledger", "Transaction boundaries" 1).

A write validates, saves the fact in one Unit of Work and commits once. It touches nothing
else: no processing state and no job (user decision 2026-10-19, staleness removed from the
project, OQ-31; processing runs only when the user requests it).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, Instrument
from di1.modules.ledger.application.ports import LedgerRepository
from di1.modules.ledger.domain.entries import (
    EntryDraft,
    EntryType,
    LedgerEntry,
    LedgerEntryView,
    NewCashMovement,
    NewTrade,
    validate_cash_movement,
    validate_deletion,
    validate_trade,
)
from di1.modules.ledger.domain.listing import (
    EntryCursor,
    LedgerEntryPage,
    ListOrder,
    PageRequest,
    validate_page_request,
)
from di1.modules.pricing.public import PricingService, Quote, QuoteFields, validate_quote
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail, unknown_asset
from di1.shared.input_kind import InputKind
from di1.shared.paging import PageParams

logger = logging.getLogger(__name__)

TRADE_QUOTE_FIELDS = QuoteFields(reference_date="date", pu="execution_pu", rate="execution_rate")
"""The request fields the client keys a trade's quote errors on (frontend ``ledger.ts``)."""


def validate_new_trade(
    draft: EntryDraft, *, today: date, maturity_date: date | None, known: bool
) -> tuple[ErrorDetail, ...]:
    """Every problem of a TRADE draft: Ledger's rules, then Pricing's one quote validation on the
    trade request's fields (OQ-34). ``known`` is whether ``draft.asset_id`` names a contract,
    whose maturity is ``maturity_date``."""
    errors = validate_trade(draft, today=today, known=known)
    if draft.input_kind is None:
        return errors
    return errors + validate_quote(
        draft.input_kind,
        pu=draft.execution_pu,
        rate=draft.execution_rate,
        reference_date=draft.entry_date,
        maturity_date=maturity_date if known else None,
        fields=TRADE_QUOTE_FIELDS,
    )


class LedgerService:
    """Ledger on one request's Unit of Work: each write commits it once."""

    def __init__(
        self,
        repository: LedgerRepository,
        uow: UnitOfWork,
        *,
        clock: Clock,
        assets: AssetReader,
        pricing: PricingService,
    ) -> None:
        self._repository = repository
        self._uow = uow
        self._clock = clock
        self._assets = assets
        self._pricing = pricing

    async def create_entry(self, draft: EntryDraft) -> LedgerEntryView:
        """Record a trade or a cash movement. Raises `DomainError` for an invalid entry; nothing
        is written then."""
        if draft.type is EntryType.CASH:
            return await self._create_cash_movement(draft)
        return await self._create_trade(draft)

    async def delete_entries(self, ids: Collection[UUID]) -> None:
        """Delete entries of either type for good, in one transaction, all or nothing (OQ-24;
        user decision 2026-10-19). An id that names no entry raises ``NOT_FOUND`` and deletes
        nothing."""
        existing = await self._repository.lock_existing(ids)
        errors = validate_deletion(ids, existing)
        if errors:
            raise DomainError(*errors)
        to_delete = tuple(dict.fromkeys(ids))
        await self._repository.delete(to_delete)
        await self._uow.commit()
        logger.info("deleted %d ledger entries", len(to_delete))

    async def list_entries(
        self,
        *,
        start_date: date,
        end_date: date,
        search: str | None,
        order: ListOrder,
        page: PageParams,
    ) -> LedgerEntryPage:
        """One page of the entries of both types dated in [start_date, end_date],
        ordered by (entry_date, entry_time, seq) (OQ-24, OQ-26 item 1). Writes nothing."""
        errors = validate_page_request(start_date=start_date, end_date=end_date, page=page)
        if errors:
            raise DomainError(*errors)
        request = PageRequest.of(
            start_date=start_date, end_date=end_date, search=search, order=order, page=page
        )
        matching: set[UUID] = set()
        if request.search is not None:
            traded = await self._repository.trade_asset_ids(request.start_date, request.end_date)
            instruments = await self._assets.get_instruments(traded) if traded else {}
            matching = {i.id for i in instruments.values() if request.search.matches_code(i.code)}
        rows = await self._repository.page(request, matching_asset_ids=matching)
        has_more = len(rows) > request.limit
        rows = rows[: request.limit]
        asset_ids = {row.asset_id for row in rows if row.asset_id is not None}
        instruments = await self._assets.get_instruments(asset_ids) if asset_ids else {}
        last = rows[-1] if has_more else None
        return LedgerEntryPage(
            items=[_view(row, instruments) for row in rows],
            next_cursor=(
                None
                if last is None
                else EntryCursor(last.entry_date, last.entry_time, last.seq).encode()
            ),
        )

    async def _create_cash_movement(self, draft: EntryDraft) -> LedgerEntryView:
        errors = validate_cash_movement(draft, today=self._clock.today())
        if errors or draft.cash_amount is None:  # a missing amount always comes with errors
            raise DomainError(*errors)
        movement = NewCashMovement(draft.entry_date, draft.entry_time, draft.cash_amount)
        entry = await self._repository.add_cash_movement(movement)
        await self._uow.commit()
        return LedgerEntryView(entry, asset_code=None, instrument_type_code=None)

    async def _create_trade(self, draft: EntryDraft) -> LedgerEntryView:
        instrument = await self._instrument(draft.asset_id)
        errors = validate_new_trade(
            draft,
            today=self._clock.today(),
            maturity_date=None if instrument is None else instrument.maturity_date,
            known=instrument is not None,
        )
        kind, quantity = draft.input_kind, draft.signed_quantity
        typed = draft.execution_pu if kind is InputKind.PU else draft.execution_rate
        # Each missing piece always comes with its own error.
        if errors or instrument is None or kind is None or quantity is None or typed is None:
            raise DomainError(*errors)
        try:
            price = await self._pricing.calculate(
                instrument.id, draft.entry_date, Quote(kind, typed)
            )
        except DomainError as error:
            raise _as_request_error(error) from error
        # The typed value is stored as typed (OQ-3); only the other one comes from Pricing.
        trade = NewTrade(
            entry_date=draft.entry_date,
            entry_time=draft.entry_time,
            asset_id=instrument.id,
            signed_quantity=quantity,
            input_kind=kind,
            execution_pu=typed if kind is InputKind.PU else price.pu,
            execution_rate=price.rate if kind is InputKind.PU else typed,
        )
        entry = await self._repository.add_trade(trade)
        await self._uow.commit()
        return LedgerEntryView(entry, instrument.code, instrument.instrument_type)

    async def _instrument(self, asset_id: UUID | None) -> Instrument | None:
        """The contract, or ``None`` when the request names none or an unknown one: a body field,
        so a validation error on it rather than ``NOT_FOUND``."""
        if asset_id is None:
            return None
        return (await self._assets.get_instruments([asset_id])).get(asset_id)


def _as_request_error(error: DomainError) -> DomainError:
    """Pricing's refusal, named after the request's fields. An instrument Pricing cannot find is
    a body field, so a validation error on ``asset_id``, never a 404."""
    details = [
        unknown_asset()
        if detail.code is ErrorCode.NOT_FOUND
        else ErrorDetail(detail.code, detail.message, TRADE_QUOTE_FIELDS.from_pricing(detail.field))
        for detail in error.errors
    ]
    return DomainError(*details, detail=error.detail if len(details) > 1 else None)


def _view(entry: LedgerEntry, instruments: Mapping[UUID, Instrument]) -> LedgerEntryView:
    if entry.asset_id is None:
        return LedgerEntryView(entry, asset_code=None, instrument_type_code=None)
    # The foreign key guarantees the contract exists.
    descriptor = instruments[entry.asset_id]
    return LedgerEntryView(entry, descriptor.code, descriptor.instrument_type)
