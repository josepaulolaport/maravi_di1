"""Ledger's public contract: trades and cash movements as other modules read them
(interfaces.md "Ledger").

Frozen in W0.3b. The public row is `LedgerEntry` (one table, OQ-24). Portfolio and PnL map it
to their own domain inputs in their application layer. Lane C implements `LedgerReader`;
changes go through the integrator.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from di1.modules.ledger.domain.entries import EntryType as EntryType
from di1.modules.ledger.domain.entries import LedgerEntry as LedgerEntry

__all__ = ["EntryType", "LedgerEntry", "LedgerReader"]


class LedgerReader(Protocol):
    """Read access for Portfolio and Processing over ``ledger.entries``. Ranges are inclusive
    calendar dates. A deleted entry no longer exists (hard delete, OQ-32)."""

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        """TRADE rows dated in [start_date, end_date], ordered by `LedgerEntry.order_key`."""
        ...

    async def get_cash_movements(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        """CASH rows dated in [start_date, end_date], ordered by `LedgerEntry.order_key`."""
        ...

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        """Whether any entry is dated on or before ``day``: of ``entry_type``, or of either type
        when ``None``. Processing's zero-state check (OQ-31, OQ-37): positions ask for
        ``EntryType.TRADE``, cash for any type."""
        ...
