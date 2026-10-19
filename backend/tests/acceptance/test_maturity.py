"""Maturity (spec §7.4; OQ-1): no automatic settlement; the user closes with a normal trade, here
on the maturity date (PU typed, rate 0); the maturity-day reference price is the user's; after
maturity the reference PU is 0 by definition and an open position loses Q × (0 − PU_maturity).
Pricing's own maturity rules (rate 0, typed rate or later date rejected) are covered over HTTP in
phase 2.

DI1F27 matures on Wednesday 06/01/2027.
    Tue 05/01  buy 2 @ 99980, reference 99985   trades 2 × 5 = 10; cash −199960; AUM 10
    Wed 06/01  sell 1 @ 100000 (maturity), reference 100000 (typed by the user)
               position 2 × (100000 − 99985) = 30; trades −1 × 0 = 0; cumulative 40
               cash −199960 + 100000 = −99960; MV 1 × 100000; AUM 40
    Thu 07/01  1 still open, reference PU 0 by definition
               position 1 × (0 − 100000) = −100000; cumulative −99960; MV 0; AUM −99960
    Fri 08/01  position 1 × (0 − 0) = 0
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.public import (
    AssetValuationInput,
    ReferenceSource,
    ValuationCalculator,
    ValuationStatus,
)
from tests.acceptance.harness import DI1F27, MATURITIES, Facts, run, trade

TUESDAY = date(2027, 1, 5)
MATURITY = date(2027, 1, 6)
THURSDAY = date(2027, 1, 7)
FRIDAY = date(2027, 1, 8)

FACTS = Facts(
    trades=[
        trade(DI1F27, TUESDAY, 2, "99980", "0.09"),
        trade(DI1F27, MATURITY, -1, "100000", "0"),
    ],
    prices={(DI1F27, TUESDAY): Decimal("99985"), (DI1F27, MATURITY): Decimal("100000")},
)


def test_maturity_is_the_harness_contract_date() -> None:
    assert MATURITIES[DI1F27] == MATURITY


def test_a_reference_price_after_maturity_is_rejected() -> None:
    with pytest.raises(ValueError, match="no reference price is accepted after maturity"):
        ValuationCalculator().calculate_day(
            THURSDAY,
            [AssetValuationInput(DI1F27, 1, MATURITY, Decimal("1"), ReferenceSource.MANUAL)],
            cash_balance=Decimal(0),
        )


def test_close_on_the_maturity_date_and_leave_one_open() -> None:
    days = run(FACTS, TUESDAY, FRIDAY)

    assert days[TUESDAY].pnl.cumulative_pnl == Decimal("10")
    assert days[TUESDAY].aum == Decimal("10")

    maturity = days[MATURITY]
    assert maturity.position(DI1F27).quantity == 1
    assert maturity.asset_pnl[DI1F27].position_pnl == Decimal("30")
    assert maturity.asset_pnl[DI1F27].trades_pnl == 0
    assert maturity.pnl.cumulative_pnl == Decimal("40")
    assert maturity.cash.cash_balance == Decimal("-99960")
    assert maturity.valued(DI1F27).financial_total == Decimal("100000")
    assert maturity.aum == Decimal("40")


def test_after_maturity_the_value_is_zero_and_the_open_position_loses_its_pu() -> None:
    days = run(FACTS, TUESDAY, FRIDAY)

    thursday = days[THURSDAY]
    assert thursday.expected_assets == {DI1F27}  # still open: Q[D−1] = 1
    assert thursday.valued(DI1F27).reference_pu == 0
    assert thursday.valued(DI1F27).financial_total == 0
    assert thursday.valued(DI1F27).status is ValuationStatus.COMPLETE
    assert thursday.asset_pnl[DI1F27].position_pnl == Decimal("-100000")
    assert thursday.pnl.daily_pnl == Decimal("-100000")
    assert thursday.pnl.cumulative_pnl == Decimal("-99960")
    assert thursday.aum == Decimal("-99960")

    friday = days[FRIDAY]
    assert friday.asset_pnl[DI1F27].position_pnl == 0
    assert friday.pnl.cumulative_pnl == Decimal("-99960")
    assert friday.pnl.status is CalculationCompleteness.COMPLETE


def test_without_the_maturity_day_price_the_figures_are_null() -> None:
    facts = Facts(trades=FACTS.trades, prices={(DI1F27, TUESDAY): Decimal("99985")})

    days = run(facts, TUESDAY, THURSDAY)

    maturity = days[MATURITY]
    assert maturity.valued(DI1F27).financial_total is None
    assert maturity.asset_pnl[DI1F27].position_pnl is None
    assert maturity.pnl.daily_pnl is None
    # The day after needs the maturity-day PU as its D−1 price: still null, chain broken.
    thursday = days[THURSDAY]
    assert thursday.valued(DI1F27).financial_total == 0
    assert thursday.asset_pnl[DI1F27].position_pnl is None
    assert thursday.pnl.cumulative_pnl is None
