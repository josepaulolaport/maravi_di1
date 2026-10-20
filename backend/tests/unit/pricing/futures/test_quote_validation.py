"""The one validation of a DI1 quote typed as a PU or a rate, before anything is priced.

Pricing owns it; Ledger and Prices call it through ``pricing.public`` with their own request field
names, and the calculator runs the same rule on Pricing's names (code-review finding H3).

Rules: exactly one of the PU or the rate is typed, the one ``kind`` names (spec §4.1); a typed PU
has at most 10 places and a typed rate at most 12, more is rejected, never rounded (OQ-3); the
bounds are only the schema's, PU > 0 and rate > −1 (OQ-14); a date after the maturity is
``CONTRACT_MATURED`` and on the maturity date the PU is typed, so a rate is refused with one
message (OQ-1). Every problem is reported at once.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.pricing.public import QuoteFields, validate_quote
from di1.shared.errors import ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

MATURITY = date(2028, 1, 3)
BEFORE = date(2026, 10, 16)
PU = Decimal("89250.3147019396")
RATE = Decimal("0.1")

PRICING_NAMES = QuoteFields()
"""Pricing's own field names: ``reference_date``, ``pu``, ``rate``."""


def invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


def check(
    kind: InputKind,
    *,
    pu: Decimal | None = None,
    rate: Decimal | None = None,
    reference_date: date = BEFORE,
    maturity_date: date | None = MATURITY,
    fields: QuoteFields = PRICING_NAMES,
) -> tuple[Decimal | None, tuple[ErrorDetail, ...]]:
    """The typed value when the quote is valid (``None`` otherwise), and its problems."""
    errors = validate_quote(
        kind,
        pu=pu,
        rate=rate,
        reference_date=reference_date,
        maturity_date=maturity_date,
        fields=fields,
    )
    typed = pu if kind is InputKind.PU else rate
    return (None if errors else typed), errors


# --- accepted ----------------------------------------------------------------------------------


def test_a_typed_pu_is_returned_as_typed() -> None:
    value, errors = check(InputKind.PU, pu=Decimal("82057.00"))

    assert errors == ()
    assert str(value) == "82057.00"  # trailing zeros kept (OQ-3)


def test_a_typed_rate_is_returned_as_typed() -> None:
    value, errors = check(InputKind.RATE, rate=Decimal("0.100000000000"))

    assert errors == ()
    assert str(value) == "0.100000000000"


def test_the_limits_are_accepted() -> None:
    assert check(InputKind.PU, pu=Decimal("0.0000000001"))[1] == ()
    assert check(InputKind.RATE, rate=Decimal("-0.999999999999"))[1] == ()


def test_the_maturity_date_with_a_typed_pu_is_accepted() -> None:
    value, errors = check(InputKind.PU, pu=Decimal("100000"), reference_date=MATURITY)

    assert (value, errors) == (Decimal("100000"), ())


def test_without_a_known_maturity_only_the_value_is_checked() -> None:
    # Ledger reports an unknown contract on its own field and still checks the typed value.
    assert check(InputKind.RATE, rate=RATE, maturity_date=None) == (RATE, ())
    assert check(InputKind.PU, pu=Decimal("-1"), maturity_date=None)[1] == (
        invalid("O PU deve ser maior que zero.", "pu"),
    )


# --- presence: exactly the typed value (spec §4.1) ---------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (InputKind.PU, invalid("Informe o PU.", "pu")),
        (InputKind.RATE, invalid("Informe a taxa.", "rate")),
    ],
)
def test_the_typed_value_is_required(kind: InputKind, expected: ErrorDetail) -> None:
    assert check(kind) == (None, (expected,))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (InputKind.PU, invalid("Informe apenas o PU, sem a taxa.", "rate")),
        (InputKind.RATE, invalid("Informe apenas a taxa, sem o PU.", "pu")),
    ],
)
def test_the_other_value_is_never_typed_too(kind: InputKind, expected: ErrorDetail) -> None:
    assert check(kind, pu=PU, rate=RATE) == (None, (expected,))


# --- typed precision (OQ-3) and bounds (OQ-14) ---------------------------------------------------


@pytest.mark.parametrize("pu", ["89250.31470193960", "90909.09090909091"])
def test_a_pu_with_more_than_10_places_is_rejected_not_rounded(pu: str) -> None:
    # Trailing zeros were typed, so they count.
    assert check(InputKind.PU, pu=Decimal(pu)) == (
        None,
        (invalid("Use no máximo 10 casas decimais.", "pu"),),
    )


@pytest.mark.parametrize("rate", ["0.1000000000000", "0.1000000000001", "0.0000000000005"])
def test_a_rate_with_more_than_12_places_is_rejected_not_rounded(rate: str) -> None:
    assert check(InputKind.RATE, rate=Decimal(rate)) == (
        None,
        (invalid("Use no máximo 12 casas decimais.", "rate"),),
    )


@pytest.mark.parametrize("pu", ["0", "0.0000000000", "-1", "-90909.09"])
def test_a_pu_must_be_positive(pu: str) -> None:
    assert check(InputKind.PU, pu=Decimal(pu)) == (
        None,
        (invalid("O PU deve ser maior que zero.", "pu"),),
    )


@pytest.mark.parametrize("rate", ["-1", "-1.5", "-100"])
def test_a_rate_must_be_above_minus_one(rate: str) -> None:
    assert check(InputKind.RATE, rate=Decimal(rate)) == (
        None,
        (invalid("A taxa deve ser maior que −100%.", "rate"),),
    )


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_a_value_that_is_not_finite_is_rejected(value: str) -> None:
    assert check(InputKind.PU, pu=Decimal(value)) == (
        None,
        (invalid("Informe um número válido.", "pu"),),
    )
    assert check(InputKind.RATE, rate=Decimal(value)) == (
        None,
        (invalid("Informe um número válido.", "rate"),),
    )


# --- maturity (OQ-1) ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "pu", "rate"), [(InputKind.PU, PU, None), (InputKind.RATE, None, RATE)]
)
def test_a_date_after_the_maturity_is_contract_matured(
    kind: InputKind, pu: Decimal | None, rate: Decimal | None
) -> None:
    assert check(kind, pu=pu, rate=rate, reference_date=date(2028, 1, 4)) == (
        None,
        (
            ErrorDetail(
                ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "reference_date"
            ),
        ),
    )


@pytest.mark.parametrize(
    ("pu", "rate"),
    [
        (None, RATE),
        (None, None),
        (None, Decimal("0.1234567890123")),
        (None, Decimal("-2")),
        (PU, None),
        (PU, RATE),
    ],
)
def test_on_the_maturity_date_a_rate_gets_one_message_on_the_rate(
    pu: Decimal | None, rate: Decimal | None
) -> None:
    # The rate is not typed on that date at all, so a missing or invalid rate, or "informe
    # apenas a taxa" for a PU sent too, would contradict "informe o PU".
    assert check(InputKind.RATE, pu=pu, rate=rate, reference_date=MATURITY) == (
        None,
        (invalid("Na data de vencimento informe o PU.", "rate"),),
    )


def test_every_problem_is_reported_at_once() -> None:
    _, errors = check(InputKind.PU, pu=Decimal("-1"), rate=RATE, reference_date=date(2028, 1, 4))

    assert set(errors) == {
        ErrorDetail(
            ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "reference_date"
        ),
        invalid("Informe apenas o PU, sem a taxa.", "rate"),
        invalid("O PU deve ser maior que zero.", "pu"),
    }


# --- the caller's field names (OQ-34) -------------------------------------------------------------

LEDGER_NAMES = QuoteFields(reference_date="date", pu="execution_pu", rate="execution_rate")


def test_errors_are_reported_on_the_callers_fields() -> None:
    assert {e.field for e in check(InputKind.PU, pu=PU, rate=RATE, fields=LEDGER_NAMES)[1]} == {
        "execution_rate"
    }
    assert check(InputKind.RATE, rate=RATE, reference_date=MATURITY, fields=LEDGER_NAMES)[1] == (
        invalid("Na data de vencimento informe o PU.", "execution_rate"),
    )
    assert check(InputKind.PU, pu=PU, reference_date=date(2028, 1, 4), fields=LEDGER_NAMES)[1] == (
        ErrorDetail(ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "date"),
    )


@pytest.mark.parametrize(
    ("pricing_field", "request_field"),
    [
        ("reference_date", "date"),
        ("pu", "execution_pu"),
        ("rate", "execution_rate"),
        ("asset_id", "asset_id"),
        (None, None),
    ],
)
def test_a_pricing_field_is_renamed_to_the_callers(
    pricing_field: str | None, request_field: str | None
) -> None:
    # The calculator reports on Pricing's names; a caller renames them with the same fields.
    assert LEDGER_NAMES.from_pricing(pricing_field) == request_field
