"""Decimal precision and rounding shared by every module (OQ-3; spec §4.1).

- Arithmetic uses a 34-digit context with ROUND_HALF_UP (halfway away from zero).
- A calculated PU is stored with 10 decimal places, a calculated rate with 12.
- A typed value with more decimals than stored is rejected, never rounded: the predicate tells
  the caller whether it fits.
- Storing never fails for a finite value the schema accepts (unbounded NUMERIC; OQ-14 bounds
  are only the schema's), never yields a negative zero, and never mutates shared state.
- Values leave the backend in plain notation, never exponent form (CLAUDE.md §2).
- Mixing a float into financial arithmetic raises (CLAUDE.md §2: never float).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    FloatOperation,
    Inexact,
    Rounded,
    getcontext,
    localcontext,
)

import pytest

from di1.contracts.decimals import (
    DECIMAL_CONTEXT,
    PU_PLACES,
    RATE_PLACES,
    financial_context,
    fits_places,
    quantize_pu,
    quantize_rate,
    to_plain,
)

Quantizer = Callable[[Decimal], Decimal]


def test_context_has_34_digits_and_rounds_half_up() -> None:
    assert (DECIMAL_CONTEXT.prec, DECIMAL_CONTEXT.rounding) == (34, "ROUND_HALF_UP")
    assert (PU_PLACES, RATE_PLACES) == (10, 12)


def test_financial_context_applies_the_context_and_restores_the_previous_one() -> None:
    with localcontext() as outer:
        outer.prec, outer.rounding = 5, ROUND_HALF_EVEN
        with financial_context():
            third = Decimal(1) / Decimal(3)
            assert getcontext().rounding == "ROUND_HALF_UP"
        assert (getcontext().prec, getcontext().rounding) == (5, ROUND_HALF_EVEN)
    assert third == Decimal("0." + "3" * 34)


def test_challenge_pu_is_stored_with_10_places() -> None:
    # Challenge §3: 10% a.a., 365 calendar days → PU = 100000 / 1.1 = 90909.0909090909...
    with financial_context():
        pu = Decimal("100000") / Decimal("1.1")
    assert quantize_pu(pu) == Decimal("90909.0909090909")


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("0.00000000005", "0.0000000001"),  # halfway rounds away from zero
        ("-0.00000000005", "-0.0000000001"),
        ("0.000000000049999", "0.0000000000"),
        ("100000", "100000.0000000000"),
    ],
)
def test_pu_rounds_half_up_to_10_places(value: str, stored: str) -> None:
    result = quantize_pu(Decimal(value))
    assert (result, result.as_tuple().exponent) == (Decimal(stored), -10)


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("0.1000000000005", "0.100000000001"),
        ("0.1000000000004", "0.100000000000"),
        ("-0.0000000000005", "-0.000000000001"),
        ("0.1", "0.100000000000"),
    ],
)
def test_rate_rounds_half_up_to_12_places(value: str, stored: str) -> None:
    result = quantize_rate(Decimal(value))
    assert (result, result.as_tuple().exponent) == (Decimal(stored), -12)


@pytest.mark.parametrize(
    ("value", "places", "fits"),
    [
        ("90909.0909090909", 10, True),
        ("90909.09090909091", 10, False),
        ("0.135", 12, True),
        ("0.1234567890123", 12, False),
        ("100", 10, True),
        ("1E+2", 10, True),
        ("1E-12", 12, True),
        ("1E-13", 12, False),
        ("0.10000000000000", 12, False),  # trailing zeros are typed decimals too
        ("NaN", 10, False),
        ("Infinity", 10, False),
    ],
)
def test_fits_places_tells_whether_a_typed_value_is_accepted(
    value: str, places: int, fits: bool
) -> None:
    assert fits_places(Decimal(value), places) is fits


@pytest.mark.parametrize("function", [quantize_pu, quantize_rate])
@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_quantize_rejects_non_finite_values(function: Quantizer, value: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        function(Decimal(value))


@pytest.mark.parametrize(
    ("function", "value", "exponent"),
    [
        (quantize_pu, "1E+24", -10),
        (quantize_rate, "1E+22", -12),
        # rate from PU = 1 over 30 days: (100000 / 1)^(365/30) − 1 ≈ 1E+60
        (quantize_rate, "1.000000000000000000000000000000000E+60", -12),
    ],
)
def test_storing_a_value_beyond_34_digits_keeps_it_exactly(
    function: Quantizer, value: str, exponent: int
) -> None:
    result = function(Decimal(value))
    assert (result, result.as_tuple().exponent) == (Decimal(value), exponent)


def test_input_with_more_than_34_digits_is_rounded_once_at_storage() -> None:
    assert quantize_pu(Decimal("90909.090909090909090909090909090909090909")) == Decimal(
        "90909.0909090909"
    )


@pytest.mark.parametrize(
    ("function", "value"), [(quantize_rate, "-1E-13"), (quantize_pu, "-0.0000000000001")]
)
def test_a_value_that_rounds_to_zero_is_stored_without_sign(
    function: Quantizer, value: str
) -> None:
    result = function(Decimal(value))
    assert result == 0
    assert result.is_signed() is False


def test_quantize_leaves_the_shared_context_untouched() -> None:
    DECIMAL_CONTEXT.clear_flags()
    quantize_pu(Decimal(1) / Decimal(3))
    assert not DECIMAL_CONTEXT.flags[Inexact]
    assert not DECIMAL_CONTEXT.flags[Rounded]


@pytest.mark.parametrize(
    ("value", "plain"),
    [
        ("0E-12", "0.000000000000"),
        ("1E-10", "0.0000000001"),
        ("-1E-10", "-0.0000000001"),
        ("1E+2", "100"),
        ("90909.0909090909", "90909.0909090909"),
    ],
)
def test_to_plain_never_uses_exponent_form(value: str, plain: str) -> None:
    assert to_plain(Decimal(value)) == plain


def test_to_plain_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        to_plain(Decimal("NaN"))


def test_a_float_in_financial_arithmetic_raises() -> None:
    with financial_context(), pytest.raises(FloatOperation):
        Decimal(0.1)  # noqa: RUF032  # the float is the mistake under test
    with financial_context(), pytest.raises(FloatOperation):
        _ = Decimal("1") < 1.5  # the float comparison is the mistake under test
