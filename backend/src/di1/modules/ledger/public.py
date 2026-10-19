"""Ledger's public contract: trades and cash movements as other modules read them
(interfaces.md "Ledger").

Frozen in W0.3b. Ledger owns these facts; Portfolio and PnL map them to their own domain inputs
in their application layer. Lane C implements `LedgerReader`; changes go through the
integrator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from di1.shared.input_kind import InputKind


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One active trade: a TRADE row of ``ledger.entries`` (OQ-24).

    ``signed_quantity`` is positive for a buy and negative for a sell, never 0 (spec §7.2).
    ``execution_pu``/``execution_rate`` are the execution price, never a reference price
    (spec §4.2); on the maturity date the PU is typed and the rate is 0 (OQ-1). ``trade_time``
    is São Paulo local time. Its cash effect, −signed_quantity × execution_pu, is not stored.
    """

    id: UUID
    asset_id: UUID
    trade_date: date
    trade_time: time
    seq: int
    signed_quantity: int
    execution_pu: Decimal
    execution_rate: Decimal
    input_kind: InputKind
    created_at: datetime

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order of ledger entries: (date, time, seq) (OQ-13, OQ-24)."""
        return (self.trade_date, self.trade_time, self.seq)


@dataclass(frozen=True, slots=True)
class CashMovementRecord:
    """One active cash movement: a CASH row of ``ledger.entries`` (OQ-24).

    ``amount`` is exact and signed: positive for a deposit (aporte), negative for a withdrawal
    (retirada), never 0. Deposits and withdrawals are never P&L.
    """

    id: UUID
    movement_date: date
    movement_time: time
    seq: int
    amount: Decimal
    created_at: datetime

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order of ledger entries: (date, time, seq) (OQ-13, OQ-24)."""
        return (self.movement_date, self.movement_time, self.seq)


class LedgerReader(Protocol):
    """Read access for Portfolio and Processing over ``ledger.entries``. Ranges are inclusive
    calendar dates; deleted entries are never returned."""

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[TradeRecord]:
        """Active trades dated in [start_date, end_date], ordered by `TradeRecord.order_key`."""
        ...

    async def get_cash_movements(
        self, start_date: date, end_date: date
    ) -> Sequence[CashMovementRecord]:
        """Active cash movements dated in [start_date, end_date], ordered by
        `CashMovementRecord.order_key`."""
        ...
