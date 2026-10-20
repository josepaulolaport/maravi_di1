"""Market value (spec §8.2, §8.3, §7.4; §13 items 7 and 8; §15 I3; OQ-1, OQ-2, OQ-10).

financial_total = Q × reference_PU; positions_market_value = Σ financial_total. A missing required
price leaves the dependent figures null, never zero. AUM = cash + market value is computed on read
(OQ-50 item 1). The maturity rule is resolved before valuation: its tests are in test_maturity.py.
"""

from __future__ import annotations

from datetime import date
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

ZERO = Decimal("0")


def _asset(
    quantity: int,
    reference_pu: str | None,
    *,
    asset_id: UUID = DI1F27,
) -> AssetValuationInput:
    return AssetValuationInput(
        asset_id=asset_id,
        quantity=quantity,
        reference_pu=None if reference_pu is None else Decimal(reference_pu),
    )


def test_the_challenge_example_has_market_value_90909_09() -> None:
    # Challenge §5 (spec §15 I3, D2): 1 DI1F28 at reference 10% → PU 90909.0909090909.
    on = date(2027, 1, 1)
    result = value_positions(
        on,
        [_asset(1, "90909.0909090909", asset_id=DI1F28)],
    )

    assert result.assets[0].financial_total == Decimal("90909.0909090909")
    assert result.positions_market_value == Decimal("90909.0909090909")
    assert result.status is ValuationStatus.COMPLETE


def test_a_short_position_has_a_negative_market_value() -> None:
    # Spec §8.2: the quantity is signed. −5 × 95000 = −475000.
    result = value_positions(DAY, [_asset(-5, "95000")])

    assert result.assets[0].financial_total == Decimal("-475000")


def test_market_value_sums_every_expected_asset() -> None:
    # 2 × 95000 + (−1 × 91000) = 99000
    result = value_positions(DAY, [_asset(2, "95000"), _asset(-1, "91000", asset_id=DI1F28)])

    assert [a.asset_id for a in result.assets] == [DI1F27, DI1F28]
    assert result.positions_market_value == Decimal("99000")


def test_a_missing_price_leaves_the_asset_value_null_never_zero() -> None:
    result = value_positions(DAY, [_asset(3, None)])

    asset = result.assets[0]
    assert asset.financial_total is None
    assert asset.reference_pu is None
    assert asset.status is ValuationStatus.MISSING


def test_one_missing_asset_leaves_the_portfolio_total_null() -> None:
    # Spec §8.3: the total is not complete if any expected asset is missing; no partial sum.
    result = value_positions(DAY, [_asset(2, "95000"), _asset(1, None, asset_id=DI1F28)])

    assert result.assets[0].financial_total == Decimal("190000")
    assert result.assets[1].financial_total is None
    assert result.positions_market_value is None
    assert result.status is ValuationStatus.MISSING


def test_a_flat_position_is_worth_zero_without_a_price() -> None:
    # Spec §8.3: the market value of a zero position is zero even without a reference.
    result = value_positions(DAY, [_asset(0, None)])

    asset = result.assets[0]
    assert asset.financial_total == Decimal("0")
    assert asset.status is ValuationStatus.NOT_REQUIRED
    assert result.positions_market_value == Decimal("0")
    assert result.status is ValuationStatus.COMPLETE


def test_a_flat_position_with_a_price_keeps_the_price_and_is_worth_zero() -> None:
    result = value_positions(DAY, [_asset(0, "95000")])

    asset = result.assets[0]
    assert asset.reference_pu == Decimal("95000")
    assert asset.financial_total == Decimal("0")
    assert not asset.financial_total.is_signed()


def test_without_assets_the_market_value_is_zero() -> None:
    result = value_positions(DAY, [])

    assert result.assets == ()
    assert result.positions_market_value == Decimal("0")
    assert result.status is ValuationStatus.COMPLETE


def test_an_open_position_at_a_zero_pu_is_worth_zero_and_complete() -> None:
    # OQ-1: after maturity the caller resolves the PU to 0 (maturity.reference_pu_on); the
    # contract is then worth 0, and a short at 0 is not a negative zero.
    result = value_positions(DAY, [_asset(-4, "0")])

    asset = result.assets[0]
    assert asset.reference_pu == Decimal("0")
    assert asset.financial_total == Decimal("0")
    assert not asset.financial_total.is_signed()
    assert asset.status is ValuationStatus.COMPLETE


def test_the_multiplier_is_not_applied() -> None:
    # OQ-2: the formula uses the PU directly; 1 contract at 95000 is worth 95000.
    result = value_positions(DAY, [_asset(1, "95000")])

    assert result.positions_market_value == Decimal("95000")


def test_the_same_asset_twice_is_rejected() -> None:
    with pytest.raises(PortfolioError):
        value_positions(DAY, [_asset(1, "95000"), _asset(2, "95000")])
