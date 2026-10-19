"""Average entry PU and average entry rate (spec §7.2; OQ-3).

Each average is weighted by absolute quantity on its own: the average rate is never derived from
the average PU. A partial reduction keeps the average; a full close leaves none; a trade crossing
zero opens the remainder at the trade's own PU and rate. Within a day trades compound at full
precision; at the day's close the averages are rounded as stored (PU 10 places, rate 12), and the
next day starts from the rounded values, so results never depend on how a range is split.
"""

from __future__ import annotations

from decimal import Decimal

from di1.modules.portfolio.domain.errors import AccountingError
from di1.shared.decimals import financial_context, quantize_pu, quantize_rate


def next_average(
    previous_quantity: int, average: Decimal | None, traded_quantity: int, price: Decimal
) -> Decimal | None:
    """The average after one trade of ``traded_quantity`` at ``price`` (a PU or a rate)."""
    current_quantity = previous_quantity + traded_quantity
    if previous_quantity == 0:
        return price
    if average is None:
        raise AccountingError("a held position must carry an average entry price")
    if (previous_quantity > 0) == (traded_quantity > 0):
        held, added = abs(previous_quantity), abs(traded_quantity)
        with financial_context():
            return (held * average + added * price) / (held + added)
    if current_quantity == 0:
        return None
    if (current_quantity > 0) != (previous_quantity > 0):
        return price  # crossing zero: the remainder opens at the trade's price
    return average  # partial reduction keeps the average


def closing_average_pu(average: Decimal | None) -> Decimal | None:
    """The average PU as stored at the day's close: 10 places, half-up (OQ-3)."""
    return None if average is None else quantize_pu(average)


def closing_average_rate(average: Decimal | None) -> Decimal | None:
    """The average rate as stored at the day's close: 12 places, half-up (OQ-3)."""
    return None if average is None else quantize_rate(average)
