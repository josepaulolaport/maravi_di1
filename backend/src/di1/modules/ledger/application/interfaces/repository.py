"""What Ledger's services need from persistence (implemented in ``infrastructure/persistence``)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.modules.ledger.domain.entries import LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest
from di1.modules.ledger.public import CashMovementRecord, TradeRecord


class LedgerRepository(Protocol):
    """``ledger.entries`` within one transaction (the Unit of Work's session)."""

    async def add_trade(
        self, trade: NewTrade, *, execution_pu: Decimal, execution_rate: Decimal
    ) -> LedgerEntry:
        """Insert a trade with its execution price; returns the stored row (id, seq, time)."""
        ...

    async def add_cash_movement(self, movement: NewCashMovement) -> LedgerEntry: ...

    async def lock_existing(self, ids: Collection[UUID]) -> set[UUID]:
        """Which of ``ids`` name an entry, those entries locked until the transaction ends."""
        ...

    async def delete(self, ids: Collection[UUID]) -> None: ...

    async def trade_asset_ids(self, start_date: date, end_date: date) -> set[UUID]:
        """The contracts of the trades dated in the range."""
        ...

    async def page(
        self, request: PageRequest, *, matching_asset_ids: Collection[UUID]
    ) -> Sequence[LedgerEntry]:
        """Up to ``request.limit + 1`` entries after the cursor, in the requested order."""
        ...

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[TradeRecord]: ...

    async def get_cash_movements(
        self, start_date: date, end_date: date
    ) -> Sequence[CashMovementRecord]: ...
