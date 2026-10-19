"""Portfolio's input view of a trade (ports and adapters).

Ledger owns trades. ``Trade`` holds only what the positions and cash chains read; Portfolio's
application layer maps Ledger's public ``TradeRecord`` onto it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from uuid import UUID

from di1.modules.portfolio.domain.errors import AccountingError


@dataclass(frozen=True)
class Trade:
    """What accounting reads from a Ledger trade. ``signed_quantity`` is positive for a buy and
    negative for a sell; ``execution_pu`` and ``execution_rate`` are the execution price, never a
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
            raise AccountingError("a trade quantity cannot be zero")

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order of trades: (trade_date, trade_time, seq) (OQ-13)."""
        return (self.trade_date, self.trade_time, self.seq)


def day_trades(trades: Iterable[Trade], on: date) -> list[Trade]:
    """``on``'s trades in chronological order; a trade dated another day is rejected."""
    ordered = sorted(trades, key=lambda t: t.order_key)
    if any(t.trade_date != on for t in ordered):
        raise AccountingError(f"every trade must be dated {on}")
    return ordered


def trades_by_date(trades: Sequence[Trade]) -> dict[date, list[Trade]]:
    """Trades grouped by their trade date, each group in input order."""
    grouped: dict[date, list[Trade]] = {}
    for t in trades:
        grouped.setdefault(t.trade_date, []).append(t)
    return grouped
