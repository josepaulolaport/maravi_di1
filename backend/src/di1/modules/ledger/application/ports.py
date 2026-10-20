"""What `LedgerService` needs from persistence (implemented in ``infrastructure/persistence``).
Other modules read entries through ``ledger.public.LedgerReader``."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from di1.modules.ledger.domain.entries import LedgerEntry, NewCashMovement, NewTrade
from di1.modules.ledger.domain.listing import PageRequest


class LedgerRepository(Protocol):
    """``ledger.entries`` within one transaction (the Unit of Work's session)."""

    async def add_trade(self, trade: NewTrade) -> LedgerEntry:
        """Insert a trade; returns the stored row (id, seq, created_at)."""
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
