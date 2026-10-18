"""The economic facts of one trade, read by every module that consumes trades.

Ledger owns trades: it records, validates and soft-deletes them. Portfolio (accounting), PnL
(trades P&L) and Processing (which passes them between the two) read the same facts, so the value
type is defined once here instead of being redeclared in each module. Ledger's record metadata
(id, input kind, created_at, deletion audit) stays in Ledger's own DTO.

Standard library only: domain code imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Trade:
    """One trade as executed. ``signed_quantity`` is positive for a buy and negative for a sell
    (spec §7.3); ``execution_pu`` and ``execution_rate`` are the execution price, never a
    reference price (spec §4.2)."""

    asset_id: UUID
    trade_date: date
    trade_time: time
    seq: int
    signed_quantity: int
    execution_pu: Decimal
    execution_rate: Decimal

    def __post_init__(self) -> None:
        if self.signed_quantity == 0:
            raise ValueError("a trade quantity cannot be zero")

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order of trades: (trade_date, trade_time, seq) (OQ-13)."""
        return (self.trade_date, self.trade_time, self.seq)
