"""Per-asset daily P&L attribution (spec §8.1, §8.3, §13 items 5 and 7; OQ-1, OQ-2, OQ-4).

position_pnl = Q[D-1] × (PU_D − PU_{D-1})
trades_pnl   = Σ q_i × (PU_D − PU_exec_i)
daily_pnl    = position_pnl + trades_pnl

Expected values are worked by hand from those formulas; the multiplier is not applied (OQ-2).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from di1.modules.pnl.domain.asset_pnl import calculate_asset_pnl
from di1.modules.pnl.domain.results import (
    AssetPnLResult,
    CalculationCompleteness,
    MissingReferencePrice,
    PnLTrade,
)

D = Decimal
PREVIOUS = MissingReferencePrice.PREVIOUS
CURRENT = MissingReferencePrice.CURRENT

Legs = tuple[tuple[int, str], ...]


def calculate(
    previous_quantity: int,
    trades: Legs,
    previous_reference_pu: str | None,
    current_reference_pu: str | None,
) -> AssetPnLResult:
    return calculate_asset_pnl(
        previous_position=previous_quantity,
        day_trades=[PnLTrade(signed_quantity=q, execution_pu=D(pu)) for q, pu in trades],
        previous_reference_pu=None if previous_reference_pu is None else D(previous_reference_pu),
        current_reference_pu=None if current_reference_pu is None else D(current_reference_pu),
    )


def _optional(value: str | None) -> Decimal | None:
    return None if value is None else D(value)


@pytest.mark.parametrize(
    ("previous_quantity", "trades", "previous_pu", "current_pu", "position", "trades_pnl", "daily"),
    [
        # 10 × (90100 − 90000) = 1000; no trades.
        pytest.param(10, (), "90000", "90100", "1000", "0", "1000", id="long-held-pu-up"),
        # −5 × (90100 − 90000) = −500.
        pytest.param(-5, (), "90000", "90100", "-500", "0", "-500", id="short-held-pu-up"),
        # OQ-4: Q[D-1] = 0 → position_pnl = 0 (not null), no D-1 price. 10 × (90050 − 90000).
        pytest.param(0, ((10, "90000"),), None, "90050", "0", "500", "500", id="first-day-buy"),
        # Challenge §5 with D2: 1 DI1F28 at 10% (PU 90909.0909090909), reference at the same 10%.
        pytest.param(
            0,
            ((1, "90909.0909090909"),),
            None,
            "90909.0909090909",
            "0",
            "0",
            "0",
            id="challenge-example-bought-at-the-reference",
        ),
        # 10 × (90100 − 90000) + (−10) × (90100 − 90200) = 1000 + 1000 = 2000.
        pytest.param(
            0,
            ((10, "90000"), (-10, "90200")),
            None,
            "90100",
            "0",
            "2000",
            "2000",
            id="same-day-round-trip",
        ),
        # Held 10, PU 90000 → 90100: 1000. Buy 5 @ 90050: 250. Sell 3 @ 90150: −3 × (−50) = 150.
        pytest.param(
            10,
            ((5, "90050"), (-3, "90150")),
            "90000",
            "90100",
            "1000",
            "400",
            "1400",
            id="increase-and-partial-reduction",
        ),
        # Held 10, 90000 → 89900: −1000. Sell 15 @ 89950, one trade: −15 × (89900 − 89950) = 750.
        pytest.param(
            10, ((-15, "89950"),), "90000", "89900", "-1000", "750", "-250", id="long-reversed"
        ),
        # Held −10, 90000 → 89900: 1000. Buy 15 @ 89950, one trade: 15 × (89900 − 89950) = −750.
        pytest.param(
            -10, ((15, "89950"),), "90000", "89900", "1000", "-750", "250", id="short-reversed"
        ),
        # Held −10, 90000 → 90100: −1000. Buy 4 @ 90050: 4 × 50 = 200.
        pytest.param(
            -10, ((4, "90050"),), "90000", "90100", "-1000", "200", "-800", id="short-bought-back"
        ),
        # −5 × (90000 − 90000) is −0 in Decimal; the results never carry the sign.
        pytest.param(
            -5, ((-1, "90000"),), "90000", "90000", "0", "0", "0", id="short-unchanged-pu"
        ),
        # 3 × (90909.1000000001 − 90909.0909090909) = 3 × 0.0090909092 = 0.0272727276; not rounded.
        pytest.param(
            3,
            (),
            "90909.0909090909",
            "90909.1000000001",
            "0.0272727276",
            "0",
            "0.0272727276",
            id="exact-at-stored-pu-precision",
        ),
        pytest.param(0, (), None, None, "0", "0", "0", id="flat-without-trades-needs-no-price"),
        # OQ-1: the day after maturity the reference PU is 0. 10 × (0 − 99990) = −999900.
        pytest.param(10, (), "99990", "0", "-999900", "0", "-999900", id="day-after-maturity"),
        pytest.param(10, (), "0", "0", "0", "0", "0", id="later-days-after-maturity"),
    ],
)
def test_a_complete_day_attributes_position_and_trades_pnl(
    previous_quantity: int,
    trades: Legs,
    previous_pu: str | None,
    current_pu: str | None,
    position: str,
    trades_pnl: str,
    daily: str,
) -> None:
    result = calculate(previous_quantity, trades, previous_pu, current_pu)

    assert result.status is CalculationCompleteness.COMPLETE
    assert result.missing_prices == frozenset()
    figures = (result.position_pnl, result.trades_pnl, result.daily_pnl)
    assert figures == (D(position), D(trades_pnl), D(daily))
    for value in figures:  # stored and serialised values never carry a negative zero
        assert value is not None
        assert value < 0 or not value.is_signed()


@pytest.mark.parametrize(
    (
        "previous_quantity",
        "trades",
        "previous_pu",
        "current_pu",
        "missing",
        "position",
        "trades_pnl",
    ),
    [
        pytest.param(
            10, ((2, "90000"),), "90000", None, {CURRENT}, None, None, id="open-without-pu-d"
        ),
        # trades_pnl depends only on PU_D: 2 × (90100 − 90000) = 200.
        pytest.param(
            10, ((2, "90000"),), None, "90100", {PREVIOUS}, None, "200", id="open-without-pu-d-1"
        ),
        # No trades: trades_pnl is the empty sum, 0, and depends on no price.
        pytest.param(-4, (), None, None, {PREVIOUS, CURRENT}, None, "0", id="open-without-both"),
        # §8.3: flat market value is 0, but the day's trades still need PU_D.
        pytest.param(
            0,
            ((10, "90000"), (-10, "90200")),
            None,
            None,
            {CURRENT},
            "0",
            None,
            id="round-trip-without-pu-d",
        ),
        pytest.param(
            0, ((10, "90000"),), None, None, {CURRENT}, "0", None, id="first-day-without-pu-d"
        ),
    ],
)
def test_a_missing_price_nulls_the_figures_that_need_it(
    previous_quantity: int,
    trades: Legs,
    previous_pu: str | None,
    current_pu: str | None,
    missing: set[MissingReferencePrice],
    position: str | None,
    trades_pnl: str | None,
) -> None:
    # §8.3: null, never zero; the daily P&L needs both components.
    result = calculate(previous_quantity, trades, previous_pu, current_pu)

    assert result.status is CalculationCompleteness.MISSING
    assert result.missing_prices == frozenset(missing)
    assert (result.position_pnl, result.trades_pnl, result.daily_pnl) == (
        _optional(position),
        _optional(trades_pnl),
        None,
    )
