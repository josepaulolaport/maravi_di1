"""Trades P&L of one asset on day D (spec §8.1, §8.3).

    trades_pnl = Σ q_i × (PU_D − PU_exec_i)

Every trade is marked against the day's reference PU, so a same-day round trip still needs PU_D;
without it the result is ``None``, never 0. A day without trades is the empty sum, 0, and needs no
price. The multiplier is not applied (OQ-2).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from di1.modules.pnl.domain.results import PnLTrade, unsigned_zero
from di1.shared.decimals import financial_context


def calculate_trades_pnl(
    day_trades: Sequence[PnLTrade], current_reference_pu: Decimal | None
) -> Decimal | None:
    if not day_trades:
        return Decimal(0)
    if current_reference_pu is None:
        return None
    with financial_context():
        return unsigned_zero(
            sum(
                (t.signed_quantity * (current_reference_pu - t.execution_pu) for t in day_trades),
                Decimal(0),
            )
        )
