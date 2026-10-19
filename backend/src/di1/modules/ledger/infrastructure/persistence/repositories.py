"""``ledger.entries`` through one session: rows in, `LedgerEntry` and the public records out.
No business rule lives here."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.ledger.domain.entries import EntryType, LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest
from di1.modules.ledger.infrastructure.persistence.queries import entries as queries
from di1.modules.ledger.public import CashMovementRecord, TradeRecord
from di1.shared.input_kind import InputKind


class SqlLedgerRepository:
    """Satisfies `LedgerRepository` and `di1.modules.ledger.public.LedgerReader`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_trade(
        self, trade: NewTrade, *, execution_pu: Decimal, execution_rate: Decimal
    ) -> LedgerEntry:
        return await self._insert(
            {
                "type": EntryType.TRADE.value,
                "entry_date": trade.entry_date,
                "entry_time": trade.entry_time,
                "asset_id": trade.asset_id,
                "signed_quantity": trade.signed_quantity,
                "execution_pu": execution_pu,
                "execution_rate": execution_rate,
                "input_kind": trade.input_kind.value,
            }
        )

    async def add_cash_movement(self, movement: NewCashMovement) -> LedgerEntry:
        return await self._insert(
            {
                "type": EntryType.CASH.value,
                "entry_date": movement.entry_date,
                "entry_time": movement.entry_time,
                "cash_amount": movement.amount,
            }
        )

    async def lock_existing(self, ids: Collection[UUID]) -> set[UUID]:
        return set(await self._session.scalars(queries.ids_for_update(ids)))

    async def delete(self, ids: Collection[UUID]) -> None:
        await self._session.execute(queries.delete_entries(ids))

    async def trade_asset_ids(self, start_date: date, end_date: date) -> set[UUID]:
        result = await self._session.scalars(queries.trade_asset_ids(start_date, end_date))
        return set(result)

    async def page(
        self, request: PageRequest, *, matching_asset_ids: Collection[UUID]
    ) -> Sequence[LedgerEntry]:
        result = await self._session.execute(queries.page(request, matching_asset_ids))
        return [_entry(row) for row in result]

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[TradeRecord]:
        result = await self._session.execute(
            queries.entries_of_type(EntryType.TRADE, start_date, end_date)
        )
        return [_trade_record(row) for row in result]

    async def get_cash_movements(
        self, start_date: date, end_date: date
    ) -> Sequence[CashMovementRecord]:
        result = await self._session.execute(
            queries.entries_of_type(EntryType.CASH, start_date, end_date)
        )
        return [_cash_record(row) for row in result]

    async def has_entries_on_or_before(self, day: date, *, entry_type: str | None = None) -> bool:
        """Processing's zero-state check (OQ-31, OQ-37), asked only when the chain has no status
        on any date before D (OQ-40 item 5): no date before D has any status for the chain
        (``PROCESSED``, ``PROCESSED_WITH_ISSUES``, ``RUNNING`` or ``FAILED``). Every other day is
        decided by ``processing.date_status`` alone. Positions ask for trades, cash for any type.

        ``entry_type`` is typed ``str``: any ``StrEnum`` of the entry types fits, Ledger's domain
        one and ``ledger.public.EntryType`` alike, so this satisfies `LedgerReader` whichever
        enum the contract names (the domain may not import ``public.py``). It is normalised to
        Ledger's enum first: anything but ``TRADE`` or ``CASH`` raises ``ValueError`` rather than
        reading as "no entries", which would start a chain from zero."""
        kind = EntryType(entry_type) if entry_type is not None else None
        return bool(await self._session.scalar(queries.any_on_or_before(day, kind)))

    async def _insert(self, values: dict[str, Any]) -> LedgerEntry:
        result = await self._session.execute(queries.insert_entry(values))
        return _entry(result.one())


def _entry(row: Row[Any]) -> LedgerEntry:
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
        input_kind=InputKind(row.input_kind) if row.input_kind is not None else None,
        cash_amount=row.cash_amount,
    )


def _trade_record(row: Row[Any]) -> TradeRecord:
    return TradeRecord(
        id=row.id,
        asset_id=row.asset_id,
        trade_date=row.entry_date,
        trade_time=row.entry_time,
        seq=row.seq,
        signed_quantity=row.signed_quantity,
        execution_pu=row.execution_pu,
        execution_rate=row.execution_rate,
        input_kind=InputKind(row.input_kind),
        created_at=row.created_at,
    )


def _cash_record(row: Row[Any]) -> CashMovementRecord:
    return CashMovementRecord(
        id=row.id,
        movement_date=row.entry_date,
        movement_time=row.entry_time,
        seq=row.seq,
        amount=row.cash_amount,
        created_at=row.created_at,
    )
