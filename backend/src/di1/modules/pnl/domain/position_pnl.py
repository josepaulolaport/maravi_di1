"""Position P&L of one asset on day D (spec §8.1; OQ-1, OQ-4).

    position_pnl = Q[D-1] × (PU_D − PU_{D-1})

When Q[D-1] = 0 it is exactly 0 and needs no price (OQ-4). Otherwise both exact-date reference
PUs are required, and a missing one gives ``None``, never 0 (§8.3). After maturity the caller
passes 0 as PU_D (OQ-1). The multiplier is not applied (OQ-2).
"""

from __future__ import annotations

from decimal import Decimal

from di1.modules.pnl.domain.results import unsigned_zero
from di1.shared.decimals import financial_context


def calculate_position_pnl(
    previous_quantity: int,
    previous_reference_pu: Decimal | None,
    current_reference_pu: Decimal | None,
) -> Decimal | None:
    if previous_quantity == 0:
        return Decimal(0)
    if previous_reference_pu is None or current_reference_pu is None:
        return None
    with financial_context():
        return unsigned_zero(previous_quantity * (current_reference_pu - previous_reference_pu))
