"""Market value (spec §8.2, §8.3, §7.4; §13 items 7 and 8; §15 I3; OQ-1, OQ-2, OQ-10).

financial_total = Q × reference_PU; positions_market_value = Σ financial_total. A missing required
price leaves the dependent figures null, never zero. AUM = cash + market value is computed on read
(OQ-50 item 1). The maturity rule is resolved before valuation: its tests are in test_maturity.py.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.valuation import (
    AssetValuationInput,
    ValuationStatus,
    value_positions,
)
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28

COMPLETE = ValuationStatus.COMPLETE
MISSING = ValuationStatus.MISSING
NOT_REQUIRED = ValuationStatus.NOT_REQUIRED


def _asset(asset_id: UUID, quantity: int, reference_pu: str | None) -> AssetValuationInput:
    return AssetValuationInput(
        asset_id=asset_id,
        quantity=quantity,
        reference_pu=None if reference_pu is None else Decimal(reference_pu),
    )


def _optional(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


Valued = tuple[str | None, str | None, ValuationStatus]  # reference PU, total, status


@pytest.mark.parametrize(
    ("assets", "valued", "market_value", "status"),
    [
        # Challenge §5 (spec §15 I3, D2): 1 DI1F28 at reference 10% → PU 90909.0909090909. One
        # contract is worth its PU: the multiplier is not applied (OQ-2).
        pytest.param(
            [_asset(DI1F28, 1, "90909.0909090909")],
            [("90909.0909090909", "90909.0909090909", COMPLETE)],
            "90909.0909090909",
            COMPLETE,
            id="challenge-example",
        ),
        # Spec §8.2: the quantity is signed. −5 × 95000 = −475000.
        pytest.param(
            [_asset(DI1F27, -5, "95000")],
            [("95000", "-475000", COMPLETE)],
            "-475000",
            COMPLETE,
            id="short-is-negative",
        ),
        # 2 × 95000 + (−1 × 91000) = 99000; listed in asset id order.
        pytest.param(
            [_asset(DI1F28, -1, "91000"), _asset(DI1F27, 2, "95000")],
            [("95000", "190000", COMPLETE), ("91000", "-91000", COMPLETE)],
            "99000",
            COMPLETE,
            id="sums-every-expected-asset",
        ),
        # Spec §8.3: the total is not complete if any expected asset is missing; no partial sum.
        pytest.param(
            [_asset(DI1F27, 2, "95000"), _asset(DI1F28, 1, None)],
            [("95000", "190000", COMPLETE), (None, None, MISSING)],
            None,
            MISSING,
            id="one-missing-price-nulls-the-asset-and-the-total",
        ),
        # Spec §8.3: the market value of a zero position is zero even without a reference.
        pytest.param(
            [_asset(DI1F27, 0, None)],
            [(None, "0", NOT_REQUIRED)],
            "0",
            COMPLETE,
            id="flat-without-a-price",
        ),
        pytest.param(
            [_asset(DI1F27, 0, "95000")],
            [("95000", "0", NOT_REQUIRED)],
            "0",
            COMPLETE,
            id="flat-with-a-price-keeps-it",
        ),
        # OQ-1: after maturity the caller resolves the PU to 0; a short at 0 is not a negative zero.
        pytest.param(
            [_asset(DI1F27, -4, "0")],
            [("0", "0", COMPLETE)],
            "0",
            COMPLETE,
            id="open-at-zero-pu",
        ),
        pytest.param([], [], "0", COMPLETE, id="no-assets"),
    ],
)
def test_the_market_value_sums_each_asset_quantity_times_its_reference_pu(
    assets: list[AssetValuationInput],
    valued: list[Valued],
    market_value: str | None,
    status: ValuationStatus,
) -> None:
    result = value_positions(DAY, assets)

    assert [(a.reference_pu, a.financial_total, a.status) for a in result.assets] == [
        (_optional(pu), _optional(total), s) for pu, total, s in valued
    ]
    for asset in result.assets:  # never "-0" in JSON
        total = asset.financial_total
        assert total is None or total < 0 or not total.is_signed()
    assert result.positions_market_value == _optional(market_value)
    assert result.status is status


def test_the_same_asset_twice_is_rejected() -> None:
    with pytest.raises(PortfolioError):
        value_positions(DAY, [_asset(DI1F27, 1, "95000"), _asset(DI1F27, 2, "95000")])
