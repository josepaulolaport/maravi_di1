"""Every calendar day is processed (spec §7.1): each chain starts D from the close of D−1.

Neither chain accepts a state from two days back, so a skipped day cannot pass silently.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from di1.modules.portfolio.domain.cash import ZERO, CashBalance, CashCalculator
from di1.modules.portfolio.domain.errors import AccountingError
from di1.modules.portfolio.domain.positions import PositionsEngine, PositionState
from tests.unit.portfolio.factories import DAY

TWO_DAYS_BEFORE = DAY - timedelta(days=2)
SKIPPED = f"the previous state must be of {DAY - timedelta(days=1)}, not {TWO_DAYS_BEFORE}"


def test_the_positions_chain_refuses_to_skip_a_day() -> None:
    with pytest.raises(AccountingError, match=SKIPPED):
        PositionsEngine().calculate_day(PositionState.zero(TWO_DAYS_BEFORE), [], DAY)


def test_the_cash_chain_refuses_to_skip_a_day() -> None:
    with pytest.raises(AccountingError, match=SKIPPED):
        CashCalculator().calculate_day(CashBalance.zero(TWO_DAYS_BEFORE), [], ZERO, ZERO, DAY)
