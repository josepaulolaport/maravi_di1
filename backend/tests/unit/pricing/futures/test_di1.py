"""DI1 calculator (DC/365): PU = face / (1 + taxa)^(d/365) and taxa = (face / PU)^(365/d) − 1,
with d the calendar days from the reference date to the maturity; exactly one typed input (rate
or PU), the other calculated and quantized as stored (PU 10 dp, rate 12 dp, half-up); typed
values with excess decimals rejected; on the maturity date the PU is typed and the rate is 0;
dates after the maturity rejected; multiplier not applied.

Refs: spec §4.1, §7.4, §13 item 1, §15 D4; interfaces "Pricing"; schema.md (face value);
OQ-1, OQ-2, OQ-3, OQ-7, OQ-14.

Expected values are worked by hand from the formula (exponents that are whole numbers), or come
from the challenge example; the property tests compare with an independent exp/ln evaluation at
60 digits.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st

from di1.modules.pricing.domain.errors import (
    ContractMaturedError,
    InvalidPricingInputError,
    PricingError,
)
from di1.modules.pricing.domain.futures.di1 import DI1Calculator
from di1.modules.pricing.domain.futures.model import (
    FuturesTerms,
    InputKind,
    Price,
    Quote,
)

FACE = Decimal("100000")
MATURITY = date(2028, 1, 1)
calculator = DI1Calculator()


def price(reference_date: date, quote: Quote, face: Decimal = FACE) -> Price:
    return calculator.calculate(FuturesTerms(MATURITY, face), reference_date, quote)


def days_before_maturity(days: int) -> date:
    return MATURITY - timedelta(days=days)


# --- Challenge example (desafio §5; spec §15 D4) ----------------------------------------------


def test_challenge_example_rate_10_percent_365_days_gives_the_challenge_pu() -> None:
    # DI1F28 bought on 01/01/2027 at 10% a.a., maturity 01/01/2028: 365 calendar days.
    result = price(date(2027, 1, 1), Quote.rate(Decimal("0.10")))

    assert result.pu == Decimal("90909.0909090909")
    assert result.rate == Decimal("0.10")
    assert result.input_kind is InputKind.RATE


def test_challenge_pu_back_to_the_rate_is_10_percent() -> None:
    result = price(date(2027, 1, 1), Quote.pu(Decimal("90909.0909090909")))

    assert result.rate == Decimal("0.100000000000")
    assert result.pu == Decimal("90909.0909090909")
    assert result.input_kind is InputKind.PU


# --- Rate → PU, hand-worked values --------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "days", "pu"),
    [
        ("0", 100, "100000.0000000000"),  # 1^x = 1
        ("-0.5", 365, "200000.0000000000"),  # 100000 / 0.5
        ("1", 730, "25000.0000000000"),  # 100000 / 2^2
        ("0.10", 730, "82644.6280991736"),  # 100000 / 1.21 = 82644.62809917355371…
        ("0.21", 365, "82644.6280991736"),  # same discount over one year
    ],
)
def test_pu_from_rate(rate: str, days: int, pu: str) -> None:
    result = price(days_before_maturity(days), Quote.rate(Decimal(rate)))

    assert result.pu == Decimal(pu)
    assert result.rate == Decimal(rate)  # the typed value is kept as typed


def test_calculated_pu_has_exactly_10_places() -> None:
    result = price(days_before_maturity(100), Quote.rate(Decimal("0")))

    assert result.pu.as_tuple().exponent == -10


def test_face_value_is_the_numerator() -> None:
    # 1000 / 1.1 = 909.090909090909…
    result = price(date(2027, 1, 1), Quote.rate(Decimal("0.10")), face=Decimal("1000"))

    assert result.pu == Decimal("909.0909090909")


# --- PU → rate, hand-worked values --------------------------------------------------------------


@pytest.mark.parametrize(
    ("pu", "days", "rate"),
    [
        ("100000", 10, "0.000000000000"),  # 1^x − 1
        ("200000", 365, "-0.500000000000"),  # 0.5 − 1
        ("25000", 730, "1.000000000000"),  # 4^(1/2) − 1
        ("50000", 365, "1.000000000000"),  # 2 − 1
    ],
)
def test_rate_from_pu(pu: str, days: int, rate: str) -> None:
    result = price(days_before_maturity(days), Quote.pu(Decimal(pu)))

    assert result.rate == Decimal(rate)
    assert result.rate.as_tuple().exponent == -12
    assert result.pu == Decimal(pu)


# --- Calendar-day count (spec §4.1; OQ-7) ---------------------------------------------------------


def test_days_to_maturity_are_calendar_days() -> None:
    # The day count itself is tested in tests/unit/shared/test_calendar.py.
    # Thursday 30/12/2027 → Saturday 01/01/2028, through the year-end holiday: 2 days.
    result = price(date(2027, 12, 30), Quote.rate(Decimal("0.10")))

    assert abs(result.pu - oracle_pu(Decimal("0.10"), 2, FACE)) <= Decimal("1E-10")


def test_leap_year_uses_366_days_over_365() -> None:
    result = calculator.calculate(
        FuturesTerms(date(2029, 1, 1), FACE),
        date(2028, 1, 1),
        Quote.rate(Decimal("0.10")),
    )

    assert result.pu < Decimal("90909.0909090909")  # one more day of discount
    assert abs(result.pu - oracle_pu(Decimal("0.10"), 366, FACE)) <= Decimal("1E-10")


# --- Maturity (OQ-1, §7.4) ------------------------------------------------------------------------


def test_on_maturity_the_pu_is_typed_and_the_rate_is_zero() -> None:
    result = price(MATURITY, Quote.pu(Decimal("99987.6543")))

    assert result.pu == Decimal("99987.6543")
    assert result.rate == Decimal("0.000000000000")
    assert result.rate.as_tuple().exponent == -12


def test_on_maturity_a_typed_rate_is_rejected() -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(MATURITY, Quote.rate(Decimal("0.10")))

    assert caught.value.field == "rate"
    assert caught.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "quote",
    [Quote.rate(Decimal("0.10")), Quote.pu(Decimal("90000"))],
)
def test_a_reference_date_after_maturity_is_rejected(quote: Quote) -> None:
    with pytest.raises(ContractMaturedError) as caught:
        price(MATURITY + timedelta(days=1), quote)

    assert caught.value.code == "CONTRACT_MATURED"
    assert caught.value.field == "reference_date"


def test_one_day_before_maturity_prices_normally() -> None:
    # 100000 / 1.1^(1/365): close to face, below it.
    result = price(days_before_maturity(1), Quote.rate(Decimal("0.10")))

    assert Decimal("99970") < result.pu < FACE
    assert abs(result.pu - oracle_pu(Decimal("0.10"), 1, FACE)) <= Decimal("1E-10")


# --- Bounds: only the schema's (OQ-14) ------------------------------------------------------------


@pytest.mark.parametrize("pu", ["0", "-1", "-90909.09"])
def test_nonpositive_pu_is_rejected(pu: str) -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(date(2027, 1, 1), Quote.pu(Decimal(pu)))

    assert caught.value.field == "pu"


@pytest.mark.parametrize("rate", ["-1", "-1.5", "-100"])
def test_rate_at_or_below_minus_one_is_rejected(rate: str) -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(date(2027, 1, 1), Quote.rate(Decimal(rate)))

    assert caught.value.field == "rate"


def test_a_rate_just_above_minus_one_is_accepted() -> None:
    # 100000 / 0.000000000001 = 1E+17 over exactly one year.
    result = price(date(2027, 1, 1), Quote.rate(Decimal("-0.999999999999")))

    assert result.pu == Decimal("100000000000000000.0000000000")


@pytest.mark.parametrize("face", ["0", "-100000"])
def test_nonpositive_face_value_is_rejected(face: str) -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(date(2027, 1, 1), Quote.rate(Decimal("0.10")), face=Decimal(face))

    assert caught.value.field == "face_value"


def test_a_pu_that_would_be_stored_as_zero_is_rejected() -> None:
    # 100000 / (1E+20)^10 rounds to 0 at 10 places, which the schema forbids (PU > 0).
    with pytest.raises(InvalidPricingInputError) as caught:
        price(days_before_maturity(3650), Quote.rate(Decimal("100000000000000000000")))

    assert caught.value.field == "rate"


def test_a_rate_that_would_be_stored_as_minus_one_is_rejected() -> None:
    # (100000 / 1E+10)^365 − 1 = 1E-1825 − 1 rounds to −1 at 12 places (schema: rate > −1).
    with pytest.raises(InvalidPricingInputError) as caught:
        price(days_before_maturity(1), Quote.pu(Decimal("10000000000")))

    assert caught.value.field == "pu"


# --- Typed precision: excess decimals rejected, never rounded (OQ-3) ------------------------------


@pytest.mark.parametrize("rate", ["0.1000000000001", "0.1000000000000", "0.0000000000005"])
def test_typed_rate_with_more_than_12_places_is_rejected(rate: str) -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(date(2027, 1, 1), Quote.rate(Decimal(rate)))

    assert caught.value.field == "rate"


def test_typed_rate_with_12_places_is_accepted() -> None:
    result = price(date(2027, 1, 1), Quote.rate(Decimal("0.100000000000")))

    assert result.pu == Decimal("90909.0909090909")


@pytest.mark.parametrize("pu", ["90909.09090909091", "90909.09090909090"])
def test_typed_pu_with_more_than_10_places_is_rejected(pu: str) -> None:
    with pytest.raises(InvalidPricingInputError) as caught:
        price(date(2027, 1, 1), Quote.pu(Decimal(pu)))

    assert caught.value.field == "pu"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_non_finite_inputs_are_rejected(value: str) -> None:
    with pytest.raises(InvalidPricingInputError):
        price(date(2027, 1, 1), Quote.pu(Decimal(value)))
    with pytest.raises(InvalidPricingInputError):
        price(date(2027, 1, 1), Quote.rate(Decimal(value)))


def test_errors_share_a_base_type() -> None:
    assert issubclass(InvalidPricingInputError, PricingError)
    assert issubclass(ContractMaturedError, PricingError)


# --- Input hygiene: Decimal only, exactly one input ----------------------------------------------


def test_a_float_input_is_refused() -> None:
    with pytest.raises(TypeError):
        Quote(kind=InputKind.RATE, value=0.10)  # type: ignore[arg-type]


def test_the_input_names_its_kind() -> None:
    assert Quote.rate(Decimal("0.1")) == Quote(InputKind.RATE, Decimal("0.1"))
    assert Quote.pu(Decimal("1")) == Quote(InputKind.PU, Decimal("1"))


def test_results_do_not_depend_on_the_callers_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 5
        context.rounding = "ROUND_DOWN"
        result = price(date(2027, 1, 1), Quote.rate(Decimal("0.10")))

    assert result.pu == Decimal("90909.0909090909")


# --- Invariants: independent oracle and round trips ----------------------------------------------


def oracle_pu(rate: Decimal, days: int, face: Decimal) -> Decimal:
    """face · exp(−(d/365) · ln(1 + rate)) at 60 digits: a different numerical path."""
    with localcontext() as context:
        context.prec = 60
        return face * (-(Decimal(days) / Decimal(365)) * (1 + rate).ln()).exp()


def oracle_rate(pu: Decimal, days: int, face: Decimal) -> Decimal:
    """exp((365/d) · ln(face / PU)) − 1 at 60 digits."""
    with localcontext() as context:
        context.prec = 60
        return ((Decimal(365) / Decimal(days)) * (face / pu).ln()).exp() - 1


rates = st.decimals(min_value="-0.5", max_value="1", places=12, allow_nan=False)
# Up to 105000: a PU much above face over one day gives a rate that rounds to −1 at 12 places,
# which is rejected (test_a_rate_that_would_be_stored_as_minus_one_is_rejected).
pus = st.decimals(min_value="1000", max_value="105000", places=10, allow_nan=False)
days = st.integers(min_value=1, max_value=3650)


@given(rate=rates, d=days)
def test_pu_matches_the_oracle_to_the_stored_place(rate: Decimal, d: int) -> None:
    result = price(days_before_maturity(d), Quote.rate(rate))

    assert abs(result.pu - oracle_pu(rate, d, FACE)) <= Decimal("0.5E-10") + Decimal("1E-20")


@given(pu=pus, d=days)
def test_rate_matches_the_oracle_to_the_stored_place(pu: Decimal, d: int) -> None:
    result = price(days_before_maturity(d), Quote.pu(pu))
    expected = oracle_rate(pu, d, FACE)

    # Half a unit at 12 places, plus the 34-significant-digit context (OQ-3): the rounded base and
    # exponent carry a relative error of at most 1E-33 each, amplified by the exponent 365/d and
    # by ln(face/PU). It matters only for the huge rates a low PU gives over a few days.
    exponent = Decimal(365) / d
    with localcontext() as context:
        context.prec = 60
        amplification = 1 + exponent * (1 + abs((FACE / pu).ln()))
    tolerance = Decimal("0.5E-12") + abs(expected) * amplification * Decimal("1E-33")
    assert abs(result.rate - expected) <= tolerance


@given(rate=rates, d=days)
def test_rate_to_pu_to_rate_round_trip(rate: Decimal, d: int) -> None:
    pu = price(days_before_maturity(d), Quote.rate(rate)).pu
    back = price(days_before_maturity(d), Quote.pu(pu)).rate

    # PU stored to 10 places moves the rate by at most (365/d)·(1 + rate)·(0.5E-10 / PU) to first
    # order; storing the rate adds half a unit at 12 places.
    tolerance = Decimal(365) / d * (1 + rate) * Decimal("0.5E-10") / pu * 2 + Decimal("0.5E-12")
    assert abs(back - rate) <= tolerance


@given(pu=pus, d=days)
def test_pu_to_rate_to_pu_round_trip(pu: Decimal, d: int) -> None:
    rate = price(days_before_maturity(d), Quote.pu(pu)).rate
    back = price(days_before_maturity(d), Quote.rate(rate)).pu

    # The rate stored to 12 places moves the PU by at most PU·(d/365)·0.5E-12/(1 + rate) to first
    # order; storing the PU adds half a unit at 10 places.
    tolerance = pu * d / Decimal(365) * Decimal("0.5E-12") / (1 + rate) * 2 + Decimal("0.5E-10")
    assert abs(back - pu) <= tolerance


def test_the_multiplier_is_not_a_pricing_term() -> None:
    # OQ-2: the multiplier stays in the product registry and is not applied.
    assert {field.name for field in fields(FuturesTerms)} == {"maturity_date", "face_value"}


def test_a_float_face_value_is_refused() -> None:
    with pytest.raises(TypeError):
        FuturesTerms(MATURITY, 100000.0)  # type: ignore[arg-type]
