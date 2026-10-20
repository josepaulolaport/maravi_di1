"""Decimal precision and rounding shared by every module (OQ-3; spec §4.1; CLAUDE.md §2)."""

from __future__ import annotations

from decimal import Decimal, FloatOperation

import pytest

from di1.shared.decimals import (
    DECIMAL_CONTEXT,
    ZERO,
    financial_context,
    fits_places,
    quantize_pu,
    quantize_rate,
    to_plain,
    unsigned,
)


def test_context_has_34_digits_and_rounds_half_up() -> None:
    assert (DECIMAL_CONTEXT.prec, DECIMAL_CONTEXT.rounding) == (34, "ROUND_HALF_UP")
    with financial_context():
        assert Decimal(1) / Decimal(3) == Decimal("0." + "3" * 34)


def test_challenge_pu_is_stored_with_10_places() -> None:
    # Challenge §3: 10% a.a. over 365 calendar days → PU = 100000 / 1.1
    with financial_context():
        pu = Decimal("100000") / Decimal("1.1")
    assert quantize_pu(pu) == Decimal("90909.0909090909")


@pytest.mark.parametrize(
    ("value", "pu"),
    [("0.00000000005", "0.0000000001"), ("-0.00000000005", "-0.0000000001")],
)
def test_pu_rounds_half_away_from_zero_at_10_places(value: str, pu: str) -> None:
    assert quantize_pu(Decimal(value)) == Decimal(pu)


def test_rate_rounds_half_up_at_12_places() -> None:
    result = quantize_rate(Decimal("0.1000000000005"))
    assert (result, result.as_tuple().exponent) == (Decimal("0.100000000001"), -12)


def test_a_huge_value_is_stored_exactly() -> None:
    # Rate from PU 1 over 30 days ≈ 1E+60: allowed by the schema (OQ-14), so storing must work.
    assert quantize_rate(Decimal("1E+60")) == Decimal("1E+60")


def test_a_value_rounding_to_zero_has_no_sign() -> None:
    assert quantize_rate(Decimal("-1E-13")).is_signed() is False


def test_storing_a_non_finite_value_fails() -> None:
    with pytest.raises(ValueError, match="finite"):
        quantize_pu(Decimal("NaN"))


@pytest.mark.parametrize(
    ("value", "places", "fits"),
    [
        ("0.135", 12, True),
        ("0.1234567890123", 12, False),
        ("0.10000000000000", 12, False),  # trailing zeros were typed too
        ("1E+2", 10, True),
        ("NaN", 10, False),
    ],
)
def test_fits_places_tells_whether_a_typed_value_is_accepted(
    value: str, places: int, fits: bool
) -> None:
    assert fits_places(Decimal(value), places) is fits


@pytest.mark.parametrize(("value", "plain"), [("0E-12", "0.000000000000"), ("1E+2", "100")])
def test_to_plain_never_uses_exponent_form(value: str, plain: str) -> None:
    assert to_plain(Decimal(value)) == plain


def test_a_float_in_financial_arithmetic_raises() -> None:
    with financial_context(), pytest.raises(FloatOperation):
        Decimal(0.1)  # noqa: RUF032  # the float is the mistake under test


def test_zero_is_an_unsigned_decimal_zero() -> None:
    assert Decimal(0) == ZERO
    assert ZERO.is_signed() is False


@pytest.mark.parametrize(
    ("value", "expected"), [("-0", "0"), ("-0.00", "0.00"), ("-1.5", "-1.5"), ("2", "2")]
)
def test_unsigned_drops_only_the_sign_of_a_zero(value: str, expected: str) -> None:
    result = unsigned(Decimal(value))

    assert str(result) == expected
    assert result.is_signed() is (expected.startswith("-"))
