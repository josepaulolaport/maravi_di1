"""The reference PU around maturity (spec §5, §7.4; OQ-1), the one rule valuation, P&L and the
position table share.

Up to and including the maturity date the reference PU is the exact-date preferred price, or
none (no carry-forward). After maturity the contract is worth 0 by definition: no price is read.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

ZERO = Decimal("0")


def is_past_maturity(day: date, maturity: date | None) -> bool:
    """``True`` on every date after the maturity date; a contract may still trade and be priced
    on the maturity date itself. ``None`` is an instrument without a maturity."""
    return maturity is not None and day > maturity


def reference_pu_on(day: date, maturity: date | None, price_pu: Decimal | None) -> Decimal | None:
    """The reference PU of ``day``: ``price_pu``, the exact-date preferred price or ``None``, up to
    maturity; 0 after it, whatever price exists."""
    return ZERO if is_past_maturity(day, maturity) else price_pu
