"""Every calendar day is processed (spec §7.1): each chain starts D from the close of D−1.

Neither chain accepts a state from two days back, so a skipped day cannot pass silently.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from di1.modules.portfolio.domain.cash import CashBalance, calculate_cash_day
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import PositionState, calculate_positions_day
from di1.shared.decimals import ZERO
from tests.support.builders import DAY

TWO_DAYS_BEFORE = DAY - timedelta(days=2)
SKIPPED = f"the previous state must be of {DAY - timedelta(days=1)}, not {TWO_DAYS_BEFORE}"


def test_the_positions_chain_refuses_to_skip_a_day() -> None:
    with pytest.raises(PortfolioError, match=SKIPPED):
        calculate_positions_day(PositionState.zero(TWO_DAYS_BEFORE), [], DAY)


def test_the_cash_chain_refuses_to_skip_a_day() -> None:
    with pytest.raises(PortfolioError, match=SKIPPED):
        calculate_cash_day(CashBalance.zero(TWO_DAYS_BEFORE), [], ZERO, ZERO, DAY)
