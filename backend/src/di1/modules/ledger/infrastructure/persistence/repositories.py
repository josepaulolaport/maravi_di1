"""``ledger.entries`` through one session: rows in, `LedgerEntry` out. No business rule lives
here."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest
from di1.modules.ledger.infrastructure.persistence.models import LedgerEntryRow
from di1.modules.ledger.infrastructure.persistence.queries import entries as queries
from di1.shared.input_kind import InputKind


class SqlLedgerRepository:
    """Implements `LedgerRepository` and `ledger.public.LedgerReader` on one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_trade(self, trade: NewTrade) -> LedgerEntry:
        return _to_entry((await self._session.scalars(queries.insert_trade(trade))).one())

    async def add_cash_movement(self, movement: NewCashMovement) -> LedgerEntry:
        statement = queries.insert_cash_movement(movement)
        return _to_entry((await self._session.scalars(statement)).one())

    async def lock_existing(self, ids: Collection[UUID]) -> set[UUID]:
        return set(await self._session.scalars(queries.ids_for_update(ids)))

    async def delete(self, ids: Collection[UUID]) -> None:
        await self._session.execute(queries.delete_entries(ids))

    async def trade_asset_ids(self, start_date: date, end_date: date) -> set[UUID]:
        rows = await self._session.scalars(queries.trade_asset_ids(start_date, end_date))
        return {asset_id for asset_id in rows if asset_id is not None}

    async def page(
        self, request: PageRequest, *, matching_asset_ids: Collection[UUID]
    ) -> Sequence[LedgerEntry]:
        rows = await self._session.scalars(queries.page(request, matching_asset_ids))
        return [_to_entry(row) for row in rows]

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        return await self._of_type(EntryType.TRADE, start_date, end_date)

    async def get_cash_movements(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        return await self._of_type(EntryType.CASH, start_date, end_date)

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        """Processing's zero-state check (OQ-31, OQ-37), asked only when the chain has no status
        on any date before D (OQ-40 item 5). Positions ask for trades, cash for any type."""
        return bool(await self._session.scalar(queries.any_on_or_before(day, entry_type)))

    async def _of_type(
        self, entry_type: EntryType, start_date: date, end_date: date
    ) -> Sequence[LedgerEntry]:
        rows = await self._session.scalars(
            queries.entries_of_type(entry_type, start_date, end_date)
        )
        return [_to_entry(row) for row in rows]


def _to_entry(row: LedgerEntryRow) -> LedgerEntry:
    return LedgerEntry(
        id=row.id,
        type=EntryType(row.type),
        entry_date=row.entry_date,
        entry_time=row.entry_time,
        seq=row.seq,
        created_at=row.created_at,
        asset_id=row.asset_id,
        signed_quantity=row.signed_quantity,
        execution_pu=row.execution_pu,
        execution_rate=row.execution_rate,
        input_kind=None if row.input_kind is None else InputKind(row.input_kind),
        cash_amount=row.cash_amount,
    )
