"""Ledger's writes and its list read (interfaces.md "Ledger", "Transaction boundaries" 1).

A write validates, saves the fact and marks the dependent results stale through
`FinancialResultInvalidator` in the same Unit of Work, then commits once. It never enqueues
processing (OQ-23). The invalidation follows the type (OQ-21, OQ-24): a trade marks cash and
positions (``trades_changed``), a cash movement only cash (``cash_movements_changed``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from di1.modules.asset.public import AssetReader, InstrumentDescriptor
from di1.modules.ledger.application.interfaces.pricing import ExecutionPricer
from di1.modules.ledger.application.interfaces.repository import LedgerRepository
from di1.modules.ledger.domain.entries import (
    EntryDraft,
    EntryType,
    KnownInstrument,
    LedgerEntry,
    plan_deletion,
    validate_cash_movement,
    validate_trade,
)
from di1.modules.ledger.domain.listing import EntryCursor, ListOrder, validate_page_request
from di1.modules.processing.public import FinancialResultInvalidator
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import Clock
from di1.shared.input_kind import InputKind

logger = logging.getLogger(__name__)


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
        pricer: ExecutionPricer,
        invalidator: FinancialResultInvalidator,
        repository_for: Callable[[UnitOfWork], LedgerRepository],
    ) -> None:
        self._clock = clock
        self._assets = assets
        self._pricer = pricer
        self._invalidator = invalidator
        self._repository_for = repository_for

    async def create_entry(self, draft: EntryDraft, *, uow: UnitOfWork) -> LedgerEntryView:
        """Record a trade or a cash movement. Raises `DomainError` for an invalid entry; nothing
        is written then."""
        repository = self._repository_for(uow)
        today = self._clock.today()
        if draft.type is EntryType.CASH:
            movement = validate_cash_movement(draft, today=today)
            entry = await repository.add_cash_movement(movement)
            await self._invalidator.cash_movements_changed(entry.entry_date, uow=uow)
            await uow.commit()
            return LedgerEntryView(entry, asset_code=None, instrument_type_code=None)

        descriptor = await self._instrument(draft.asset_id)
        known = KnownInstrument(descriptor.maturity_date) if descriptor is not None else None
        trade = validate_trade(draft, today=today, instrument=known)
        price = await self._pricer.price(
            trade.asset_id, trade.entry_date, trade.input_kind, trade.typed_value
        )
        # The typed value is stored as typed (OQ-3); only the other one comes from Pricing.
        typed_pu = trade.input_kind is InputKind.PU
        entry = await repository.add_trade(
            trade,
            execution_pu=trade.typed_value if typed_pu else price.pu,
            execution_rate=price.rate if typed_pu else trade.typed_value,
        )
        await self._invalidator.trades_changed(entry.entry_date, uow=uow)
        await uow.commit()
        assert descriptor is not None
        return LedgerEntryView(entry, descriptor.code, descriptor.instrument_type)

    async def delete_entries(self, ids: Collection[UUID], *, uow: UnitOfWork) -> None:
        """Soft-delete entries of either type in one transaction, all or nothing, under one
        ``deletion_batch_id`` (OQ-24). An unknown id raises ``NOT_FOUND`` and deletes nothing;
        an entry already deleted stays as it was."""
        repository = self._repository_for(uow)
        found = await repository.lock_entries(ids)
        plan = plan_deletion(ids, found)
        if plan.entry_ids:
            batch_id = uuid.uuid4()
            await repository.soft_delete(plan.entry_ids, deletion_batch_id=batch_id)
            # Cash, when present in the plan, is dated before every trade: invalidating it first
            # takes the date_status locks in ascending date order, as a run does, so the two
            # never deadlock (interfaces.md "Transaction boundaries" 1).
            if plan.cash_movements_from is not None:
                await self._invalidator.cash_movements_changed(plan.cash_movements_from, uow=uow)
            if plan.trades_from is not None:
                await self._invalidator.trades_changed(plan.trades_from, uow=uow)
            logger.info("deleted %d ledger entries, batch %s", len(plan.entry_ids), batch_id)
        await uow.commit()

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
        """One page of the active entries of both types dated in [start_date, end_date],
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

    async def _instrument(self, asset_id: UUID | None) -> InstrumentDescriptor | None:
        """The contract, or ``None`` when the request names none or an unknown one: a body field,
        so a validation error on it rather than ``NOT_FOUND``."""
        if asset_id is None:
            return None
        return (await self._assets.get_instruments([asset_id])).get(asset_id)


def _view(entry: LedgerEntry, instruments: Mapping[UUID, InstrumentDescriptor]) -> LedgerEntryView:
    if entry.asset_id is None:
        return LedgerEntryView(entry, asset_code=None, instrument_type_code=None)
    # The foreign key guarantees the contract exists.
    descriptor = instruments[entry.asset_id]
    return LedgerEntryView(entry, descriptor.code, descriptor.instrument_type)
