"""Every calendar day is processed (spec §7.1): each chain starts D from the close of D−1.

Neither chain accepts a state from two days back (a skipped day) or from D itself (a repeated
day), so neither can pass silently.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from di1.modules.portfolio.domain.cash import CashBalance, calculate_cash_day
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import PositionState, calculate_positions_day
from di1.shared.decimals import ZERO
from tests.support.builders import DAY

WRONG_PREVIOUS = pytest.mark.parametrize(
    "previous", [DAY - timedelta(days=2), DAY], ids=["skipped-day", "repeated-day"]
)


def _refusal(previous: date) -> str:
    return f"the previous state must be of {DAY - timedelta(days=1)}, not {previous}"


@WRONG_PREVIOUS
def test_the_positions_chain_starts_from_the_day_before(previous: date) -> None:
    with pytest.raises(PortfolioError, match=_refusal(previous)):
        calculate_positions_day(PositionState.zero(previous), [], DAY)


@WRONG_PREVIOUS
def test_the_cash_chain_starts_from_the_day_before(previous: date) -> None:
    with pytest.raises(PortfolioError, match=_refusal(previous)):
        calculate_cash_day(CashBalance.zero(previous), [], ZERO, ZERO, DAY)
