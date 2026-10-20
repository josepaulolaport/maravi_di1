"""Ledger's writes and its list read (interfaces.md "Ledger", "Transaction boundaries" 1).

A write validates, saves the fact in one Unit of Work and commits once. It touches nothing
else: no processing state and no job (user decision 2026-10-19, staleness removed from the
project, OQ-31; processing runs only when the user requests it).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, Instrument
from di1.modules.ledger.application.services.repository import LedgerRepository
from di1.modules.ledger.domain.entries import (
    EntryDraft,
    EntryType,
    LedgerEntry,
    cash_description,
    entries_to_delete,
    validate_cash_movement,
    validate_trade,
)
from di1.modules.ledger.domain.listing import EntryCursor, ListOrder, validate_page_request
from di1.modules.pricing.public import PricingService, Quote, QuoteFields, QuoteValidator
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

logger = logging.getLogger(__name__)

TRADE_QUOTE_FIELDS = QuoteFields(reference_date="date", pu="execution_pu", rate="execution_rate")
"""The request fields the client keys a trade's quote errors on (frontend ``ledger.ts``)."""

validate_trade_quote = QuoteValidator(TRADE_QUOTE_FIELDS)
"""Pricing's one quote validation, reported on the trade request's fields (OQ-34)."""


@dataclass(frozen=True, slots=True)
class LedgerEntryView:
    """An entry as the Lançamentos screen shows it: a trade with its contract's code and
    instrument type (``None`` for a cash entry)."""

    entry: LedgerEntry
    asset_code: str | None
    instrument_type_code: str | None


@dataclass(frozen=True, slots=True)
class LedgerEntryPage:
    items: Sequence[LedgerEntryView]
    next_cursor: str | None


class LedgerService:
    def __init__(
        self,
        *,
        clock: Clock,
        assets: AssetReader,
        pricing: PricingService,
        repository_for: Callable[[UnitOfWork], LedgerRepository],
    ) -> None:
        self._clock = clock
        self._assets = assets
        self._pricing = pricing
        self._repository_for = repository_for

    async def create_entry(self, draft: EntryDraft, *, uow: UnitOfWork) -> LedgerEntryView:
        """Record a trade or a cash movement. Raises `DomainError` for an invalid entry; nothing
        is written then."""
        repository = self._repository_for(uow)
        today = self._clock.today()
        if draft.type is EntryType.CASH:
            amount = validate_cash_movement(draft, today=today)
            entry = await repository.add_cash_movement(
                draft, amount=amount, description=cash_description(draft)
            )
            await uow.commit()
            return LedgerEntryView(entry, asset_code=None, instrument_type_code=None)

        instrument = await self._instrument(draft.asset_id)
        typed_value = validate_trade(
            draft,
            today=today,
            known=instrument is not None,
            maturity_date=None if instrument is None else instrument.maturity_date,
            validate_quote=validate_trade_quote,
        )
        assert draft.asset_id is not None and draft.input_kind is not None
        try:
            price = await self._pricing.calculate(
                draft.asset_id, draft.entry_date, Quote(draft.input_kind, typed_value)
            )
        except DomainError as error:
            raise _as_request_error(error) from error
        # The typed value is stored as typed (OQ-3); only the other one comes from Pricing.
        typed_pu = draft.input_kind is InputKind.PU
        entry = await repository.add_trade(
            draft,
            execution_pu=typed_value if typed_pu else price.pu,
            execution_rate=price.rate if typed_pu else typed_value,
        )
        await uow.commit()
        assert instrument is not None
        return LedgerEntryView(entry, instrument.code, instrument.instrument_type)

    async def delete_entries(self, ids: Collection[UUID], *, uow: UnitOfWork) -> None:
        """Delete entries of either type for good, in one transaction, all or nothing (OQ-24;
        user decision 2026-10-19). An id that names no entry raises ``NOT_FOUND`` and deletes
        nothing."""
        repository = self._repository_for(uow)
        existing = await repository.lock_existing(ids)
        to_delete = entries_to_delete(ids, existing)
        await repository.delete(to_delete)
        await uow.commit()
        logger.info("deleted %d ledger entries", len(to_delete))

    async def list_entries(
        self,
        *,
        start_date: date,
        end_date: date,
        search: str | None,
        order: ListOrder,
        limit: int | None,
        cursor: str | None,
        uow: UnitOfWork,
    ) -> LedgerEntryPage:
        """One page of the entries of both types dated in [start_date, end_date],
        ordered by (entry_date, entry_time, seq) (OQ-24, OQ-26 item 1). Writes nothing."""
        request = validate_page_request(
            start_date=start_date,
            end_date=end_date,
            search=search,
            order=order,
            limit=limit,
            cursor=cursor,
        )
        repository = self._repository_for(uow)
        matching: set[UUID] = set()
        if request.search is not None:
            traded = await repository.trade_asset_ids(request.start_date, request.end_date)
            instruments = await self._assets.get_instruments(traded) if traded else {}
            matching = {i.id for i in instruments.values() if request.search.matches_code(i.code)}
        rows = await repository.page(request, matching_asset_ids=matching)
        has_more = len(rows) > request.limit
        rows = rows[: request.limit]
        asset_ids = {row.asset_id for row in rows if row.asset_id is not None}
        instruments = await self._assets.get_instruments(asset_ids) if asset_ids else {}
        items = [_view(row, instruments) for row in rows]
        last = rows[-1] if has_more else None
        next_cursor = (
            EntryCursor(last.entry_date, last.entry_time, last.seq).encode()
            if last is not None
            else None
        )
        return LedgerEntryPage(items=items, next_cursor=next_cursor)

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
        ErrorDetail.validation("Selecione um contrato.", "asset_id")
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
