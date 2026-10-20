"""Simplified cash: cash[D] = cash[D−1] − Σ(signed_qty × execution_PU) + deposits − withdrawals.

Spec §7.3, §15 I2 and §13 items 4 and 6. Cash movements are Ledger facts; the engine receives only
the day's deposit and withdrawal totals. P&L is never posted to cash, and cash never depends on
reference prices: the cash chain receives neither, and runs without the positions chain.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest

from di1.modules.portfolio.domain.cash import CashBalance, calculate_cash_day
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.trade import Trade
from di1.shared.decimals import ZERO
from tests.support.builders import DAY, portfolio_trade

YESTERDAY = DAY - timedelta(days=1)


@pytest.mark.parametrize(
    ("previous", "trades", "deposits", "withdrawals", "trades_cash_flow", "balance"),
    [
        # −(10 × 95000) − (−10 × 94000) = −950000 + 940000 = −10000: a losing round trip.
        pytest.param(
            "0",
            (
                portfolio_trade(10, "95000", at="09:00", seq=1),
                portfolio_trade(-10, "94000", at="10:00", seq=2),
            ),
            "0",
            "0",
            "-10000",
            "-10000",
            id="a-buy-lowers-cash-a-sell-raises-it",
        ),
        # 1000.00 + 200000.25 − 50000.50 = 150999.75
        pytest.param(
            "1000.00",
            (),
            "200000.25",
            "50000.50",
            "0",
            "150999.75",
            id="deposits-and-withdrawals",
        ),
        # 500000 − (3 × 95000) − (−1 × 96000) + 1000 − 2000 = 500000 − 189000 − 1000 = 310000.
        pytest.param(
            "500000",
            (
                portfolio_trade(3, "95000", at="09:00", seq=1),
                portfolio_trade(-1, "96000", at="10:00", seq=2),
            ),
            "1000",
            "2000",
            "-189000",
            "310000",
            id="trades-and-movements-in-one-day",
        ),
        # The schema's only bounds are its CHECKs (OQ-14); cash_balance has none.
        pytest.param(
            "0", (portfolio_trade(1, "95000"),), "0", "0", "-95000", "-95000", id="may-go-negative"
        ),
    ],
)
def test_cash_moves_by_the_trades_and_the_day_totals(
    previous: str,
    trades: tuple[Trade, ...],
    deposits: str,
    withdrawals: str,
    trades_cash_flow: str,
    balance: str,
) -> None:
    state = CashBalance(as_of=YESTERDAY, balance=Decimal(previous))

    day = calculate_cash_day(state, trades, Decimal(deposits), Decimal(withdrawals), DAY)

    assert day.previous_cash_balance == Decimal(previous)
    assert (day.deposits, day.withdrawals) == (Decimal(deposits), Decimal(withdrawals))
    assert day.trades_cash_flow == Decimal(trades_cash_flow)
    assert day.trades_cash_flow < 0 or not day.trades_cash_flow.is_signed()  # never "-0" in JSON
    assert day.cash_balance == Decimal(balance)


@pytest.mark.parametrize(("deposits", "withdrawals"), [("-0.01", "0"), ("0", "-0.01")])
def test_negative_daily_totals_are_rejected(deposits: str, withdrawals: str) -> None:
    # Each total sums positive Ledger amounts (spec §6.2), so it is never below zero.
    with pytest.raises(PortfolioError):
        calculate_cash_day(
            CashBalance.zero(YESTERDAY), [], Decimal(deposits), Decimal(withdrawals), DAY
        )


def test_a_negative_zero_total_is_stored_unsigned() -> None:
    day = calculate_cash_day(CashBalance.zero(YESTERDAY), [], Decimal("-0"), Decimal("-0.00"), DAY)

    assert not day.deposits.is_signed()
    assert not day.withdrawals.is_signed()
    assert not day.cash_balance.is_signed()


@pytest.mark.parametrize("gap", [2, 0])
def test_a_day_cannot_be_skipped_or_repeated(gap: int) -> None:
    # Every calendar day is processed (spec §7.1): a day starts from the day before.
    # The full message names both dates, so a wrong day in it fails the test too.
    expected = f"the previous state must be of {YESTERDAY}, not {DAY - timedelta(days=gap)}"
    with pytest.raises(PortfolioError, match=re.escape(expected)):
        calculate_cash_day(CashBalance.zero(DAY - timedelta(days=gap)), [], ZERO, ZERO, DAY)
