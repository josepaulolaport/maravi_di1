"""What P&L reads from a trade (spec §8.1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PnLTrade:
    """Buys positive, sells negative (schema ``INTEGER``), at the execution PU. The application
    layer maps Ledger's trade record to it."""

    signed_quantity: int
    execution_pu: Decimal
