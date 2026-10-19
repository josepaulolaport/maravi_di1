"""The challenge's own example, run exactly as written (challenge §3 and §5; spec §15 D2, D4).

01/01/2027: deposit 200.000; buy 1 DI1F28 (maturity 01/01/2028, 365 calendar days) at 10% a.a.
The user also enters a 10% reference price for DI1F28 on 01/01/2027 (D2). Expected: PU
90.909,0909…, cash 109.090,91, market value 90.909,09, AUM ("Financeiro total") 200.000.
The trade's PU is computed here by hand; Pricing's own PU ↔ rate is covered over HTTP in phase 2.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.public import ValuationStatus
from tests.acceptance.harness import DI1F28, MATURITIES, Facts, run, trade

DAY = date(2027, 1, 1)

# 100000 / 1.1 = 90909.090909090909…, stored with 10 places, half-up (OQ-3).
PU_AT_10_PERCENT = Decimal("90909.0909090909")
CENTS = Decimal("0.01")


def test_the_contract_has_365_calendar_days_to_maturity() -> None:
    assert (MATURITIES[DI1F28] - DAY).days == 365


def test_the_pu_is_the_challenge_formula_at_10_percent() -> None:
    # PU = 100000 / (1 + 0.10)^(365/365), in the 34-digit half-up context, stored at 10 places.
    with localcontext(prec=34, rounding=ROUND_HALF_UP):
        pu = Decimal("100000") / (Decimal("1") + Decimal("0.10")) ** (Decimal(365) / Decimal(365))
    assert pu.quantize(Decimal("1E-10"), rounding=ROUND_HALF_UP) == PU_AT_10_PERCENT
    assert PU_AT_10_PERCENT.quantize(CENTS, rounding=ROUND_HALF_UP) == Decimal("90909.09")


def test_position_view_on_01_01_2027() -> None:
    facts = Facts(
        trades=[trade(DI1F28, DAY, 1, str(PU_AT_10_PERCENT), "0.10")],
        deposits={DAY: Decimal("200000")},
        prices={(DI1F28, DAY): PU_AT_10_PERCENT},
    )

    result = run(facts, DAY, DAY)[DAY]

    # Cash: 0 − 1 × 90909.0909090909 + 200000 (spec §7.3); "BRL 109090.91" in the challenge.
    assert result.accounting.cash_balance == Decimal("109090.9090909091")
    assert result.accounting.cash_balance.quantize(CENTS, rounding=ROUND_HALF_UP) == Decimal(
        "109090.91"
    )
    assert result.accounting.trades_cash_flow == Decimal("-90909.0909090909")  # "-90.909,09"

    # "DI1F28 | 1 | 90.909,09": quantity, reference PU and market value (spec §8.2).
    position = result.position(DI1F28)
    assert position.quantity == 1
    assert position.average_entry_pu == PU_AT_10_PERCENT
    assert position.average_entry_rate == Decimal("0.100000000000")
    valued = result.valued(DI1F28)
    assert valued.reference_pu == PU_AT_10_PERCENT
    assert valued.financial_total == PU_AT_10_PERCENT
    assert valued.status is ValuationStatus.COMPLETE

    # "Financeiro total: 200.000" is AUM = cash + market value (spec §15 I3).
    assert result.valuation.positions_market_value == PU_AT_10_PERCENT
    assert result.valuation.aum == Decimal("200000")
    assert result.valuation.status is ValuationStatus.COMPLETE


def test_the_first_day_pnl_is_zero_and_the_deposit_is_not_pnl() -> None:
    facts = Facts(
        trades=[trade(DI1F28, DAY, 1, str(PU_AT_10_PERCENT), "0.10")],
        deposits={DAY: Decimal("200000")},
        prices={(DI1F28, DAY): PU_AT_10_PERCENT},
    )

    result = run(facts, DAY, DAY)[DAY]

    # Q[D−1] = 0: position_pnl is exactly 0 without a D−1 price (OQ-4); the trade is marked at
    # its own PU: 1 × (90909.0909090909 − 90909.0909090909) = 0. The 200.000 deposit is not P&L.
    assert result.pnl.position_pnl == 0
    assert result.pnl.trades_pnl == 0
    assert result.pnl.daily_pnl == 0
    assert result.pnl.cumulative_pnl == 0
    assert result.pnl.status is CalculationCompleteness.COMPLETE
