"""Simplified cash: cash[D] = cash[D−1] − Σ(signed_qty × execution_PU) + deposits − withdrawals.

Spec §7.3, §15 I2 and §13 items 4 and 6. Cash movements are Ledger facts; the engine receives only
the day's deposit and withdrawal totals. P&L is never posted to cash, and cash never depends on
reference prices: the engine does not receive any.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.accounting import (
    ZERO,
    AccountingError,
    AccountingState,
    PortfolioAccounting,
)
from tests.unit.portfolio.factories import DAY, DI1F28, position, trade

ACCOUNTING = PortfolioAccounting()
YESTERDAY = DAY - timedelta(days=1)


def test_the_challenge_example_leaves_109090_91_in_cash() -> None:
    # Challenge §5 (spec §15 I2, D4): deposit 200,000, buy 1 DI1F28 at 10% → PU 90909.0909090909.
    on = date(2027, 1, 1)
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(on - timedelta(days=1)),
        [trade(1, "90909.0909090909", "0.1", asset_id=DI1F28, on=on)],
        Decimal("200000.00"),
        ZERO,
        on,
    )

    assert day.cash_balance == Decimal("109090.9090909091")
    assert day.positions[0].quantity == 1


def test_a_buy_lowers_cash_and_a_sell_raises_it_whatever_the_result() -> None:
    # −(10 × 95000) − (−10 × 94000) = −950000 + 940000 = −10000: a losing round trip.
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(YESTERDAY),
        [trade(10, "95000", at="09:00", seq=1), trade(-10, "94000", at="10:00", seq=2)],
        ZERO,
        ZERO,
        DAY,
    )

    assert day.trades_cash_flow == Decimal("-10000")
    assert day.cash_balance == Decimal("-10000")


def test_deposits_and_withdrawals_move_cash_from_the_previous_balance() -> None:
    # 1000.00 + 200000.25 − 50000.50 = 150999.75
    state = AccountingState(as_of=YESTERDAY, cash_balance=Decimal("1000.00"), positions=())

    day = ACCOUNTING.calculate_day(state, [], Decimal("200000.25"), Decimal("50000.50"), DAY)

    assert day.previous_cash_balance == Decimal("1000.00")
    assert day.deposits == Decimal("200000.25")
    assert day.withdrawals == Decimal("50000.50")
    assert day.trades_cash_flow == Decimal("0")
    assert not day.trades_cash_flow.is_signed()  # never "-0" in JSON
    assert day.cash_balance == Decimal("150999.75")


def test_trades_and_cash_movements_combine_in_one_day() -> None:
    # 500000 − (3 × 95000) − (−1 × 96000) + 1000 − 2000 = 500000 − 285000 + 96000 − 1000 = 310000.
    state = AccountingState(as_of=YESTERDAY, cash_balance=Decimal("500000"), positions=())

    day = ACCOUNTING.calculate_day(
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
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(YESTERDAY), [trade(1, "95000")], ZERO, ZERO, DAY
    )

    assert day.cash_balance == Decimal("-95000")


@pytest.mark.parametrize(("deposits", "withdrawals"), [("-0.01", "0"), ("0", "-0.01")])
def test_negative_daily_totals_are_rejected(deposits: str, withdrawals: str) -> None:
    # Each total sums positive Ledger amounts (spec §6.2), so it is never below zero.
    with pytest.raises(AccountingError):
        ACCOUNTING.calculate_day(
            AccountingState.zero(YESTERDAY), [], Decimal(deposits), Decimal(withdrawals), DAY
        )


def test_an_open_position_without_trades_leaves_cash_unchanged_day_after_day() -> None:
    # Mark-to-market P&L would move every day; cash must not.
    state = AccountingState(
        as_of=YESTERDAY,
        cash_balance=Decimal("4500.00"),
        positions=(position(10, "95000", "0.105"),),
    )

    days = ACCOUNTING.calculate_range(state, [], {}, {}, DAY + timedelta(days=2))

    assert [d.cash_balance for d in days] == [Decimal("4500.00")] * 3
    assert all(d.trades_cash_flow == 0 for d in days)


def test_a_negative_zero_total_is_stored_unsigned() -> None:
    day = ACCOUNTING.calculate_day(
        AccountingState.zero(YESTERDAY), [], Decimal("-0"), Decimal("-0.00"), DAY
    )

    assert not day.deposits.is_signed()
    assert not day.withdrawals.is_signed()
    assert not day.cash_balance.is_signed()
