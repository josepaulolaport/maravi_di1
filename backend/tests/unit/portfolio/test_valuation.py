"""Market value and AUM (spec §8.2, §8.3, §7.4; §13 items 6, 7 and 8; §15 I3; OQ-1, OQ-2, OQ-10).

financial_total = Q × reference_PU; positions_market_value = Σ financial_total; AUM = cash +
positions_market_value. A missing required price leaves the dependent figures null, never zero.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.portfolio.domain.cash import CashBalance, CashCalculator
from di1.modules.portfolio.domain.errors import AccountingError
from di1.modules.portfolio.domain.valuation import (
    AssetValuationInput,
    ValuationCalculator,
    ValuationStatus,
)
from tests.unit.portfolio.factories import DAY, DI1F27, DI1F28

VALUATION = ValuationCalculator()
FAR_MATURITY = date(2028, 1, 1)
ZERO = Decimal("0")


def _asset(
    quantity: int,
    reference_pu: str | None,
    *,
    asset_id: UUID = DI1F27,
    maturity: date = FAR_MATURITY,
) -> AssetValuationInput:
    return AssetValuationInput(
        asset_id=asset_id,
        quantity=quantity,
        maturity_date=maturity,
        reference_pu=None if reference_pu is None else Decimal(reference_pu),
    )


def test_the_challenge_example_has_aum_200000() -> None:
    # Challenge §5 (spec §15 I3, D2): 1 DI1F28 at reference 10% → PU 90909.0909090909;
    # cash 109090.9090909091 + market value 90909.0909090909 = AUM 200000.
    on = date(2027, 1, 1)
    result = VALUATION.calculate_day(
        on,
        [_asset(1, "90909.0909090909", asset_id=DI1F28, maturity=date(2028, 1, 1))],
        Decimal("109090.9090909091"),
    )

    assert result.assets[0].financial_total == Decimal("90909.0909090909")
    assert result.positions_market_value == Decimal("90909.0909090909")
    assert result.aum == Decimal("200000")
    assert result.status is ValuationStatus.COMPLETE


def test_a_short_position_has_a_negative_market_value() -> None:
    # Spec §8.2: the quantity is signed. −5 × 95000 = −475000; AUM = 600000 − 475000.
    result = VALUATION.calculate_day(DAY, [_asset(-5, "95000")], Decimal("600000"))

    assert result.assets[0].financial_total == Decimal("-475000")
    assert result.aum == Decimal("125000")


def test_market_value_sums_every_expected_asset() -> None:
    # 2 × 95000 + (−1 × 91000) = 99000
    result = VALUATION.calculate_day(
        DAY, [_asset(2, "95000"), _asset(-1, "91000", asset_id=DI1F28)], Decimal("1000")
    )

    assert [a.asset_id for a in result.assets] == [DI1F27, DI1F28]
    assert result.positions_market_value == Decimal("99000")
    assert result.aum == Decimal("100000")


def test_a_missing_price_leaves_the_asset_value_null_never_zero() -> None:
    result = VALUATION.calculate_day(DAY, [_asset(3, None)], Decimal("500"))

    asset = result.assets[0]
    assert asset.financial_total is None
    assert asset.reference_pu is None
    assert asset.status is ValuationStatus.MISSING


def test_one_missing_asset_leaves_the_portfolio_total_and_aum_null() -> None:
    # Spec §8.3: the total is not complete if any expected asset is missing; no partial sum.
    result = VALUATION.calculate_day(
        DAY, [_asset(2, "95000"), _asset(1, None, asset_id=DI1F28)], Decimal("1000")
    )

    assert result.assets[0].financial_total == Decimal("190000")
    assert result.assets[1].financial_total is None
    assert result.positions_market_value is None
    assert result.aum is None
    assert result.status is ValuationStatus.MISSING


def test_a_flat_position_is_worth_zero_without_a_price() -> None:
    # Spec §8.3: the market value of a zero position is zero even without a reference.
    result = VALUATION.calculate_day(DAY, [_asset(0, None)], Decimal("700"))

    asset = result.assets[0]
    assert asset.financial_total == Decimal("0")
    assert asset.status is ValuationStatus.NOT_REQUIRED
    assert result.positions_market_value == Decimal("0")
    assert result.aum == Decimal("700")
    assert result.status is ValuationStatus.COMPLETE


def test_a_flat_position_with_a_price_keeps_the_price_and_is_worth_zero() -> None:
    result = VALUATION.calculate_day(DAY, [_asset(0, "95000")], Decimal("0"))

    asset = result.assets[0]
    assert asset.reference_pu == Decimal("95000")
    assert asset.financial_total == Decimal("0")
    assert not asset.financial_total.is_signed()


def test_without_assets_aum_is_the_cash_balance() -> None:
    result = VALUATION.calculate_day(DAY, [], Decimal("123.45"))

    assert result.assets == ()
    assert result.positions_market_value == Decimal("0")
    assert result.aum == Decimal("123.45")
    assert result.status is ValuationStatus.COMPLETE


def test_without_a_cash_balance_aum_is_null_but_market_value_stands() -> None:
    result = VALUATION.calculate_day(DAY, [_asset(1, "95000")], None)

    assert result.positions_market_value == Decimal("95000")
    assert result.aum is None
    assert result.status is ValuationStatus.COMPLETE


def test_after_maturity_the_reference_pu_is_zero_by_definition() -> None:
    # OQ-1: after maturity the contract is worth 0; no price is required.
    result = VALUATION.calculate_day(DAY, [_asset(4, None, maturity=DAY - timedelta(days=1))], ZERO)

    asset = result.assets[0]
    assert asset.reference_pu == Decimal("0")
    assert asset.financial_total == Decimal("0")
    assert asset.status is ValuationStatus.COMPLETE
    assert result.aum == Decimal("0")


def test_on_the_maturity_date_the_user_price_is_still_required() -> None:
    # OQ-1: the maturity-day reference price is entered by the user, like any other day.
    missing = VALUATION.calculate_day(DAY, [_asset(4, None, maturity=DAY)], ZERO)
    priced = VALUATION.calculate_day(DAY, [_asset(4, "100000", maturity=DAY)], ZERO)

    assert missing.assets[0].status is ValuationStatus.MISSING
    assert priced.assets[0].financial_total == Decimal("400000")


def test_a_price_after_maturity_is_rejected() -> None:
    # OQ-1: after maturity no price is required or accepted.
    with pytest.raises(AccountingError):
        VALUATION.calculate_day(DAY, [_asset(4, "95000", maturity=DAY - timedelta(days=1))], ZERO)


def test_the_multiplier_is_not_applied() -> None:
    # OQ-2: the formula uses the PU directly; 1 contract at 95000 is worth 95000.
    result = VALUATION.calculate_day(DAY, [_asset(1, "95000")], ZERO)

    assert result.positions_market_value == Decimal("95000")


def test_the_same_asset_twice_is_rejected() -> None:
    with pytest.raises(AccountingError):
        VALUATION.calculate_day(DAY, [_asset(1, "95000"), _asset(2, "95000")], ZERO)


def test_a_deposit_moves_aum_but_not_the_market_value() -> None:
    # Spec §8.2 and §13 item 6: deposits change cash and AUM, never the valuation of positions.
    # 1 × 95000 held; cash 5000 → AUM 100000; after a 1000 deposit cash 6000 → AUM 101000.
    cash = CashCalculator().calculate_day(
        CashBalance(as_of=DAY - timedelta(days=1), balance=Decimal("5000")),
        [],
        Decimal("1000"),
        ZERO,
        DAY,
    )
    held = [_asset(1, "95000")]

    before = VALUATION.calculate_day(DAY, held, cash.previous_cash_balance)
    after = VALUATION.calculate_day(DAY, held, cash.cash_balance)

    assert before.aum == Decimal("100000")
    assert after.aum == Decimal("101000")
    assert after.positions_market_value == before.positions_market_value == Decimal("95000")


def test_the_reference_price_used_is_traceable_to_its_observation() -> None:
    # CLAUDE.md §2 / OQ-9: the price used is traceable to its revision (position_metrics row).
    price_id = UUID("00000000-0000-0000-0000-0000000000aa")
    priced = AssetValuationInput(
        asset_id=DI1F27,
        quantity=1,
        maturity_date=FAR_MATURITY,
        reference_pu=Decimal("95000"),
        reference_price_id=price_id,
    )
    expired = _asset(1, None, maturity=DAY - timedelta(days=1))

    result = VALUATION.calculate_day(DAY, [priced], ZERO)
    after_maturity = VALUATION.calculate_day(DAY, [expired], ZERO)

    assert result.assets[0].reference_price_id == price_id
    assert after_maturity.assets[0].reference_price_id is None  # 0 by definition, no observation


def test_a_price_id_without_a_price_is_rejected() -> None:
    with pytest.raises(AccountingError):
        AssetValuationInput(
            asset_id=DI1F27,
            quantity=1,
            maturity_date=FAR_MATURITY,
            reference_pu=None,
            reference_price_id=UUID("00000000-0000-0000-0000-0000000000aa"),
        )
