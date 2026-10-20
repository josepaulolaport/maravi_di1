"""DI1 calculator (DC/365): PU = face / (1 + taxa)^(d/365) and taxa = (face / PU)^(365/d) − 1,
with d the calendar days from the reference date to the maturity; exactly one typed input (rate
or PU), the other calculated and quantized as stored (PU 10 dp, rate 12 dp, half-up); typed
values with excess decimals rejected; on the maturity date the PU is typed and the rate is 0;
dates after the maturity rejected. The multiplier is not a pricing term (OQ-2): the service test
shows an instrument's multiplier changes nothing.

Refs: spec §4.1, §7.4, §13 item 1, §15 D4; interfaces "Pricing"; schema.md (face value);
OQ-1, OQ-2, OQ-3, OQ-7, OQ-14.

Expected values are worked by hand from the formula (exponents that are whole numbers), or come
from the challenge example; the property tests compare with an independent exp/ln evaluation at
60 digits.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st

from di1.modules.pricing.domain import di1
from di1.modules.pricing.domain.model import DI1Terms, Price, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

FACE = Decimal("100000")
MATURITY = date(2028, 1, 1)


def price(reference_date: date, quote: Quote, face: Decimal = FACE) -> Price:
    return di1.price(DI1Terms(MATURITY, face), reference_date, quote)


def days_before_maturity(days: int) -> date:
    return MATURITY - timedelta(days=days)


def invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


def refusal(caught: pytest.ExceptionInfo[DomainError]) -> ErrorDetail:
    (detail,) = caught.value.errors
    return detail


# --- Rate → PU (spec §4.1), hand-worked values ----------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "days", "face", "pu"),
    [
        # DI1F28 bought on 01/01/2027 at 10% a.a., maturity 01/01/2028 (desafio §5; spec §15 D4).
        pytest.param("0.10", 365, "100000", "90909.0909090909", id="challenge"),
        pytest.param("0.100000000000", 365, "100000", "90909.0909090909", id="12-places-typed"),
        pytest.param("0", 100, "100000", "100000.0000000000", id="zero-rate"),  # 1^x = 1
        pytest.param("-0.5", 365, "100000", "200000.0000000000", id="negative"),  # 100000 / 0.5
        pytest.param("1", 730, "100000", "25000.0000000000", id="two-years"),  # 100000 / 2^2
        # 100000 / 1.21 = 82644.62809917355371…
        pytest.param("0.10", 730, "100000", "82644.6280991736", id="half-up"),
        pytest.param("0.21", 365, "100000", "82644.6280991736", id="same-discount"),
        # 100000 / 0.000000000001 over exactly one year: the rate just above −1 (OQ-14).
        pytest.param("-0.999999999999", 365, "100000", "1E+17", id="rate-just-above-minus-one"),
        pytest.param("0.10", 365, "1000", "909.0909090909", id="face-is-the-numerator"),
    ],
)
def test_pu_from_rate(rate: str, days: int, face: str, pu: str) -> None:
    result = price(days_before_maturity(days), Quote(InputKind.RATE, Decimal(rate)), Decimal(face))

    assert result.pu == Decimal(pu)
    assert result.pu.as_tuple().exponent == -10  # stored with 10 places (OQ-3)
    assert str(result.rate) == rate  # the typed value is kept as typed
    assert result.input_kind is InputKind.RATE


# --- PU → rate (spec §4.1), hand-worked values ----------------------------------------------------


@pytest.mark.parametrize(
    ("pu", "days", "rate"),
    [
        # The challenge PU back to its rate: 100000 / 90909.0909090909 = 1.1 + 1.1E-16.
        pytest.param("90909.0909090909", 365, "0.100000000000", id="challenge"),
        pytest.param("100000", 10, "0.000000000000", id="face"),  # 1^x − 1
        pytest.param("200000", 365, "-0.500000000000", id="negative"),  # 0.5 − 1
        pytest.param("25000", 730, "1.000000000000", id="two-years"),  # 4^(1/2) − 1
        pytest.param("50000", 365, "1.000000000000", id="one-year"),  # 2 − 1
    ],
)
def test_rate_from_pu(pu: str, days: int, rate: str) -> None:
    result = price(days_before_maturity(days), Quote(InputKind.PU, Decimal(pu)))

    assert result.rate == Decimal(rate)
    assert result.rate.as_tuple().exponent == -12  # stored with 12 places (OQ-3)
    assert str(result.pu) == pu  # the typed value is kept as typed
    assert result.input_kind is InputKind.PU


# --- Calendar-day count (spec §4.1; OQ-7) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("reference_date", "maturity_date", "days"),
    [
        # Thursday → Saturday, through the year-end holiday: no business-day calendar.
        pytest.param(date(2027, 12, 30), date(2028, 1, 1), 2, id="weekend-and-holiday"),
        pytest.param(date(2028, 1, 1), date(2029, 1, 1), 366, id="leap-year-366-over-365"),
        pytest.param(date(2027, 12, 31), date(2028, 1, 1), 1, id="one-day-before-maturity"),
    ],
)
def test_days_to_maturity_are_calendar_days(
    reference_date: date, maturity_date: date, days: int
) -> None:
    # The day count itself is tested in tests/unit/shared/test_calendar.py.
    rate = Decimal("0.10")
    result = di1.price(DI1Terms(maturity_date, FACE), reference_date, Quote(InputKind.RATE, rate))

    assert abs(result.pu - oracle_pu(rate, days, FACE)) <= Decimal("1E-10")


# --- Maturity (OQ-1, §7.4) ------------------------------------------------------------------------


def test_on_maturity_the_pu_is_typed_and_the_rate_is_zero() -> None:
    result = price(MATURITY, Quote(InputKind.PU, Decimal("99987.6543")))

    assert result.pu == Decimal("99987.6543")
    assert result.rate == Decimal("0.000000000000")
    assert result.rate.as_tuple().exponent == -12


# --- Refusals -------------------------------------------------------------------------------------
# A typed quote's own rules (presence, places, bounds, maturity) belong to `validate_quote` and are
# tested in test_quote_validation.py; one row of each shows that `price` runs it. The other rows
# are the calculator's own: the face value and a calculated value that cannot be stored.

AFTER_MATURITY = MATURITY + timedelta(days=1)
ONE_YEAR_BEFORE = date(2027, 1, 1)
PU_ROUNDS_TO_ZERO = invalid("A taxa resulta em um PU que arredonda para zero.", "rate")


@pytest.mark.parametrize(
    ("reference_date", "quote", "face", "expected"),
    [
        pytest.param(
            AFTER_MATURITY,
            Quote(InputKind.RATE, Decimal("0.10")),
            FACE,
            ErrorDetail(
                ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "reference_date"
            ),
            id="after-maturity",
        ),
        pytest.param(
            MATURITY,
            Quote(InputKind.RATE, Decimal("0.10")),
            FACE,
            invalid("Na data de vencimento informe o PU.", "rate"),
            id="rate-on-maturity",
        ),
        pytest.param(
            ONE_YEAR_BEFORE,
            Quote(InputKind.PU, Decimal("0")),
            FACE,
            invalid("O PU deve ser maior que zero.", "pu"),
            id="pu-not-positive",
        ),
        pytest.param(
            ONE_YEAR_BEFORE,
            Quote(InputKind.RATE, Decimal("-1")),
            FACE,
            invalid("A taxa deve ser maior que −100%.", "rate"),
            id="rate-at-minus-one",
        ),
        pytest.param(
            ONE_YEAR_BEFORE,
            Quote(InputKind.RATE, Decimal("0.1000000000001")),
            FACE,
            invalid("Use no máximo 12 casas decimais.", "rate"),
            id="rate-13-places",
        ),
        pytest.param(
            ONE_YEAR_BEFORE,
            Quote(InputKind.PU, Decimal("90909.09090909091")),
            FACE,
            invalid("Use no máximo 10 casas decimais.", "pu"),
            id="pu-11-places",
        ),
        pytest.param(
            ONE_YEAR_BEFORE,
            Quote(InputKind.PU, Decimal("NaN")),
            FACE,
            invalid("Informe um número válido.", "pu"),
            id="pu-not-finite",
        ),
        *(
            pytest.param(
                ONE_YEAR_BEFORE,
                Quote(InputKind.RATE, Decimal("0.10")),
                Decimal(face),
                invalid("O valor de face deve ser maior que zero.", "face_value"),
                id=f"face-{face}",
            )
            for face in ["0", "-100000", "NaN"]
        ),
        # 100000 / (1E+20)^10 rounds to 0 at 10 places, which the schema forbids (PU > 0).
        pytest.param(
            days_before_maturity(3650),
            Quote(InputKind.RATE, Decimal("100000000000000000000")),
            FACE,
            PU_ROUNDS_TO_ZERO,
            id="pu-rounds-to-zero",
        ),
        # (1E+100000)^10 overflows the context (Emax 999999): the PU is ~0, refused as above.
        pytest.param(
            days_before_maturity(3650),
            Quote(InputKind.RATE, Decimal("1E+100000")),
            FACE,
            PU_ROUNDS_TO_ZERO,
            id="discount-factor-overflows",
        ),
        # 1E+999990 / (1E-12)^(366/365) ≈ 1E+1000002 overflows the division, not the power.
        pytest.param(
            days_before_maturity(366),
            Quote(InputKind.RATE, Decimal("-0.999999999999")),
            Decimal("1E+999990"),
            invalid("A taxa resulta em um PU fora do limite de cálculo.", "rate"),
            id="pu-overflows",
        ),
        # (1E+5000 / 1E-10)^365 = 1E+1828650 overflows the context (Emax 999999).
        pytest.param(
            days_before_maturity(1),
            Quote(InputKind.PU, Decimal("0.0000000001")),
            Decimal("1E+5000"),
            invalid("O PU resulta em uma taxa fora do limite de cálculo.", "pu"),
            id="rate-overflows",
        ),
        # (100000 / 1E+10)^365 − 1 = 1E-1825 − 1 rounds to −1 at 12 places (schema: rate > −1).
        pytest.param(
            days_before_maturity(1),
            Quote(InputKind.PU, Decimal("10000000000")),
            FACE,
            invalid("O PU resulta em uma taxa que arredonda para −100%.", "pu"),
            id="rate-rounds-to-minus-one",
        ),
    ],
)
def test_a_quote_that_cannot_be_priced_is_refused(
    reference_date: date, quote: Quote, face: Decimal, expected: ErrorDetail
) -> None:
    with pytest.raises(DomainError) as caught:
        price(reference_date, quote, face)

    assert refusal(caught) == expected


# --- Input hygiene: Decimal only, exactly one input ----------------------------------------------


def test_a_float_input_is_refused() -> None:
    with pytest.raises(TypeError):
        Quote(kind=InputKind.RATE, value=0.10)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        DI1Terms(MATURITY, 100000.0)  # type: ignore[arg-type]


def test_results_do_not_depend_on_the_callers_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 5
        context.rounding = "ROUND_DOWN"
        result = price(date(2027, 1, 1), Quote(InputKind.RATE, Decimal("0.10")))

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
# which is rejected (test_a_quote_that_cannot_be_priced_is_refused[rate-rounds-to-minus-one]).
pus = st.decimals(min_value="1000", max_value="105000", places=10, allow_nan=False)
days = st.integers(min_value=1, max_value=3650)


@given(rate=rates, d=days)
def test_pu_matches_the_oracle_to_the_stored_place(rate: Decimal, d: int) -> None:
    result = price(days_before_maturity(d), Quote(InputKind.RATE, rate))

    assert abs(result.pu - oracle_pu(rate, d, FACE)) <= Decimal("0.5E-10") + Decimal("1E-20")


@given(pu=pus, d=days)
def test_rate_matches_the_oracle_to_the_stored_place(pu: Decimal, d: int) -> None:
    result = price(days_before_maturity(d), Quote(InputKind.PU, pu))
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
    pu = price(days_before_maturity(d), Quote(InputKind.RATE, rate)).pu
    back = price(days_before_maturity(d), Quote(InputKind.PU, pu)).rate

    # PU stored to 10 places moves the rate by at most (365/d)·(1 + rate)·(0.5E-10 / PU) to first
    # order; storing the rate adds half a unit at 12 places.
    tolerance = Decimal(365) / d * (1 + rate) * Decimal("0.5E-10") / pu * 2 + Decimal("0.5E-12")
    assert abs(back - rate) <= tolerance


@given(pu=pus, d=days)
def test_pu_to_rate_to_pu_round_trip(pu: Decimal, d: int) -> None:
    rate = price(days_before_maturity(d), Quote(InputKind.PU, pu)).rate
    back = price(days_before_maturity(d), Quote(InputKind.RATE, rate)).pu

    # The rate stored to 12 places moves the PU by at most PU·(d/365)·0.5E-12/(1 + rate) to first
    # order; storing the PU adds half a unit at 10 places.
    tolerance = pu * d / Decimal(365) * Decimal("0.5E-12") / (1 + rate) * 2 + Decimal("0.5E-10")
    assert abs(back - pu) <= tolerance
