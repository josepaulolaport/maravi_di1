"""Spec §13 cases 4, 5 and 6: cash from trades and movements without P&L in cash; position,
trades and daily P&L per asset, then aggregated; cumulative P&L; deposits and withdrawals change
cash and AUM but never P&L (spec §7.3, §8.1, §8.2).

Monday 04/01/2027, from zero:
    DI1F28  buy 1 @ 90000, buy 3 @ 91000, sell 2 @ 92000, sell 5 @ 93000   → Q −3
    DI1F29  buy 2 @ 82000                                                   → Q  2
Tuesday: deposit 50.000 and withdrawal 20.000, no trades.
Reference PUs: DI1F28 92500 (Mon), 92000 (Tue); DI1F29 82100 (Mon), 81900 (Tue).

Hand computation:
    Mon cash      = −(90000 + 273000 − 184000 − 465000) − 164000 = 286000 − 164000 = 122000
    Mon trades    DI1F28 = 1×2500 + 3×1500 − 2×500 − 5×(−500) = 8500;  DI1F29 = 2×100 = 200
    Mon MV        = −3×92500 + 2×82100 = −277500 + 164200 = −113300;  AUM = 8700
    Tue cash      = 122000 + 50000 − 20000 = 152000
    Tue position  DI1F28 = −3×(92000 − 92500) = 1500;  DI1F29 = 2×(81900 − 82100) = −400
    Tue MV        = −3×92000 + 2×81900 = −276000 + 163800 = −112200;  AUM = 39800
    Cumulative    8700, then 8700 + 1100 = 9800
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from di1.modules.pnl.public import CalculationCompleteness
from tests.acceptance.harness import (
    DI1F28,
    DI1F29,
    Facts,
    run,
    run_cash,
    run_positions,
    trade,
)

MONDAY = date(2027, 1, 4)
TUESDAY = date(2027, 1, 5)

FACTS = Facts(
    trades=[
        trade(DI1F28, MONDAY, 1, "90000", "0.12", at="10:00", seq=1),
        trade(DI1F28, MONDAY, 3, "91000", "0.10", at="11:00", seq=2),
        trade(DI1F28, MONDAY, -2, "92000", "0.09", at="12:00", seq=3),
        trade(DI1F28, MONDAY, -5, "93000", "0.08", at="13:00", seq=4),
        trade(DI1F29, MONDAY, 2, "82000", "0.10", at="14:00", seq=5),
    ],
    deposits={TUESDAY: Decimal("50000")},
    withdrawals={TUESDAY: Decimal("20000")},
    prices={
        (DI1F28, MONDAY): Decimal("92500"),
        (DI1F28, TUESDAY): Decimal("92000"),
        (DI1F29, MONDAY): Decimal("82100"),
        (DI1F29, TUESDAY): Decimal("81900"),
    },
)


def test_cash_is_minus_signed_quantity_times_execution_pu_plus_movements() -> None:
    days = run(FACTS, MONDAY, TUESDAY)

    monday, tuesday = days[MONDAY].cash, days[TUESDAY].cash
    assert monday.trades_cash_flow == Decimal("122000")
    assert monday.cash_balance == Decimal("122000")
    assert (tuesday.trades_cash_flow, tuesday.deposits, tuesday.withdrawals) == (
        Decimal(0),
        Decimal("50000"),
        Decimal("20000"),
    )
    assert tuesday.previous_cash_balance == Decimal("122000")
    assert tuesday.cash_balance == Decimal("152000")


def test_pnl_is_never_posted_to_cash() -> None:
    days = run(FACTS, MONDAY, TUESDAY)

    # Tuesday earns 1100 of P&L, yet cash moves only by the deposit minus the withdrawal.
    assert days[TUESDAY].pnl.daily_pnl == Decimal("1100")
    assert days[TUESDAY].cash.cash_balance - days[MONDAY].cash.cash_balance == Decimal("30000")


def test_cash_chain_runs_alone_without_positions_or_prices() -> None:
    # Cash and positions are two independent chains (OQ-21): a CASH run gives the same cash and a
    # POSITIONS run the same quantities, with no price at all.
    no_prices = Facts(trades=FACTS.trades, deposits=FACTS.deposits, withdrawals=FACTS.withdrawals)
    cash_days = run_cash(no_prices, MONDAY, TUESDAY)
    position_days = run_positions(no_prices, MONDAY, TUESDAY)

    assert [d.cash_balance for d in cash_days.values()] == [Decimal("122000"), Decimal("152000")]
    assert [[p.quantity for p in d.positions_day.positions] for d in position_days.values()] == [
        [-3, 2],
        [-3, 2],
    ]


def test_pnl_per_asset_then_aggregated() -> None:
    days = run(FACTS, MONDAY, TUESDAY)

    monday = days[MONDAY]
    assert monday.asset_pnl[DI1F28].position_pnl == 0  # Q[D−1] = 0 (OQ-4)
    assert monday.asset_pnl[DI1F28].trades_pnl == Decimal("8500")
    assert monday.asset_pnl[DI1F28].daily_pnl == Decimal("8500")
    assert monday.asset_pnl[DI1F29].trades_pnl == Decimal("200")
    assert monday.pnl.position_pnl == 0
    assert monday.pnl.trades_pnl == Decimal("8700")
    assert monday.pnl.daily_pnl == Decimal("8700")
    assert monday.pnl.cumulative_pnl == Decimal("8700")

    tuesday = days[TUESDAY]
    assert tuesday.asset_pnl[DI1F28].position_pnl == Decimal("1500")
    assert tuesday.asset_pnl[DI1F28].trades_pnl == 0
    assert tuesday.asset_pnl[DI1F29].position_pnl == Decimal("-400")
    assert tuesday.pnl.position_pnl == Decimal("1100")
    assert tuesday.pnl.trades_pnl == 0
    assert tuesday.pnl.daily_pnl == Decimal("1100")
    assert tuesday.pnl.cumulative_pnl == Decimal("9800")
    assert tuesday.pnl.status is CalculationCompleteness.COMPLETE
    assert tuesday.pnl.cumulative_status is CalculationCompleteness.COMPLETE


def test_market_value_and_aum() -> None:
    days = run(FACTS, MONDAY, TUESDAY)

    # financial_total = Q × reference PU, signed: a short has a negative market value (§8.2).
    assert days[MONDAY].valued(DI1F28).financial_total == Decimal("-277500")
    assert days[MONDAY].valued(DI1F29).financial_total == Decimal("164200")
    assert days[MONDAY].valuation.positions_market_value == Decimal("-113300")
    assert days[MONDAY].aum == Decimal("8700")
    assert days[TUESDAY].valuation.positions_market_value == Decimal("-112200")
    assert days[TUESDAY].aum == Decimal("39800")


def test_movements_change_cash_and_aum_but_not_pnl() -> None:
    without_movements = run(Facts(trades=FACTS.trades, prices=FACTS.prices), MONDAY, TUESDAY)
    with_movements = run(FACTS, MONDAY, TUESDAY)

    plain, moved = without_movements[TUESDAY], with_movements[TUESDAY]
    assert moved.pnl == plain.pnl
    assert moved.asset_pnl == plain.asset_pnl
    assert moved.cash.cash_balance - plain.cash.cash_balance == Decimal("30000")
    assert moved.aum is not None and plain.aum is not None
    assert moved.aum - plain.aum == Decimal("30000")


def test_aum_moves_by_daily_pnl_plus_net_movements() -> None:
    # From zero, AUM[D] − AUM[D−1] = daily_pnl[D] + deposits[D] − withdrawals[D] (§7.3, §8).
    days = run(FACTS, MONDAY, TUESDAY)

    monday, tuesday = days[MONDAY], days[TUESDAY]
    assert monday.aum == monday.pnl.daily_pnl
    assert monday.aum is not None and tuesday.aum is not None
    assert tuesday.aum - monday.aum == Decimal("1100") + Decimal("30000")
