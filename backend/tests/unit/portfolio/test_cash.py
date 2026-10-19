"""Simplified cash: cash[D] = cash[D−1] − Σ(signed_qty × execution_PU) + deposits − withdrawals.

Spec §7.3, §15 I2 and §13 items 4 and 6. Cash movements are Ledger facts; the engine receives only
the day's deposit and withdrawal totals. P&L is never posted to cash, and cash never depends on
reference prices: the cash chain receives neither, and runs without the positions chain.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.cash import ZERO, CashBalance, CashCalculator
from di1.modules.portfolio.domain.errors import AccountingError
from tests.unit.portfolio.factories import DAY, trade

CASH = CashCalculator()
YESTERDAY = DAY - timedelta(days=1)


def test_a_buy_lowers_cash_and_a_sell_raises_it_whatever_the_result() -> None:
    # −(10 × 95000) − (−10 × 94000) = −950000 + 940000 = −10000: a losing round trip.
    day = CASH.calculate_day(
        CashBalance.zero(YESTERDAY),
        [trade(10, "95000", at="09:00", seq=1), trade(-10, "94000", at="10:00", seq=2)],
        ZERO,
        ZERO,
        DAY,
    )

    assert day.trades_cash_flow == Decimal("-10000")
    assert day.cash_balance == Decimal("-10000")


def test_deposits_and_withdrawals_move_cash_from_the_previous_balance() -> None:
    # 1000.00 + 200000.25 − 50000.50 = 150999.75
    state = CashBalance(as_of=YESTERDAY, balance=Decimal("1000.00"))

    day = CASH.calculate_day(state, [], Decimal("200000.25"), Decimal("50000.50"), DAY)

    assert day.previous_cash_balance == Decimal("1000.00")
    assert day.deposits == Decimal("200000.25")
    assert day.withdrawals == Decimal("50000.50")
    assert day.trades_cash_flow == Decimal("0")
    assert not day.trades_cash_flow.is_signed()  # never "-0" in JSON
    assert day.cash_balance == Decimal("150999.75")


def test_trades_and_cash_movements_combine_in_one_day() -> None:
    # 500000 − (3 × 95000) − (−1 × 96000) + 1000 − 2000 = 500000 − 285000 + 96000 − 1000 = 310000.
    state = CashBalance(as_of=YESTERDAY, balance=Decimal("500000"))

    day = CASH.calculate_day(
        state,
        [trade(3, "95000", at="09:00", seq=1), trade(-1, "96000", at="10:00", seq=2)],
        Decimal("1000"),
        Decimal("2000"),
        DAY,
    )

    assert day.trades_cash_flow == Decimal("-189000")
    assert day.cash_balance == Decimal("310000")


def test_cash_may_go_negative() -> None:
    # The schema's only bounds are its CHECKs (OQ-14); cash_balance has none.
    day = CASH.calculate_day(CashBalance.zero(YESTERDAY), [trade(1, "95000")], ZERO, ZERO, DAY)

    assert day.cash_balance == Decimal("-95000")


@pytest.mark.parametrize(("deposits", "withdrawals"), [("-0.01", "0"), ("0", "-0.01")])
def test_negative_daily_totals_are_rejected(deposits: str, withdrawals: str) -> None:
    # Each total sums positive Ledger amounts (spec §6.2), so it is never below zero.
    with pytest.raises(AccountingError):
        CASH.calculate_day(
            CashBalance.zero(YESTERDAY), [], Decimal(deposits), Decimal(withdrawals), DAY
        )


def test_a_negative_zero_total_is_stored_unsigned() -> None:
    day = CASH.calculate_day(CashBalance.zero(YESTERDAY), [], Decimal("-0"), Decimal("-0.00"), DAY)

    assert not day.deposits.is_signed()
    assert not day.withdrawals.is_signed()
    assert not day.cash_balance.is_signed()
