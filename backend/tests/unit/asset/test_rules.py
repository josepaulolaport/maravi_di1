"""Asset registration rules (spec §3; schema.sql ``asset.*``; schema.md "Application invariants";
plan §4.A).

- Codes: a product code uses letters, digits and ``_ . / -``; product and instrument codes are
  stored trimmed and upper-cased (user, 2026-10-19); an instrument code is never empty; each
  within its column's length.
- Hierarchy: the futures specification (``asset.futures``) belongs only to a product whose type is
  FUTURE, and such a product always has one; an instrument of a FUTURE product needs a maturity.
- Futures: face value and multiplier are positive (the multiplier is stored, not applied: OQ-2);
  the settlement method is not blank.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from di1.modules.asset.domain.model import FuturesTerms
from di1.modules.asset.domain.rules import (
    normalize_code,
    validate_futures_for_type,
    validate_instrument_code,
    validate_maturity,
    validate_name,
    validate_product_code,
)
from di1.shared.errors import ErrorCode, ErrorDetail

DI1_TERMS = FuturesTerms(
    face_value=Decimal("100000"),
    contract_multiplier=Decimal("1"),
    settlement_method="CASH",
    settlement_description="Liquidação financeira",
)


def _fields(errors: tuple[ErrorDetail, ...]) -> list[str | None]:
    return [error.field for error in errors]


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("DI1F27", "DI1F27"), ("di1f27", "DI1F27"), ("  Di1F28 \t", "DI1F28")],
)
def test_instrument_code_is_trimmed_and_upper_cased(typed: str, stored: str) -> None:
    assert normalize_code(typed) == stored
    assert validate_instrument_code(normalize_code(typed)) == ()


@pytest.mark.parametrize("typed", ["", "   "])
def test_a_blank_instrument_code_is_rejected(typed: str) -> None:
    code = normalize_code(typed)

    assert code == ""
    assert validate_instrument_code(code) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe o código do contrato.", "code"),
    )


def test_a_nul_in_an_instrument_code_is_rejected() -> None:
    # PostgreSQL text cannot hold NUL: malformed input, never a database error.
    errors = validate_instrument_code(normalize_code("DI1\x00F27"))

    assert _fields(errors) == ["code"]
    assert errors[0].code is ErrorCode.VALIDATION_ERROR


def test_an_instrument_code_fits_its_column_of_128_characters() -> None:
    assert validate_instrument_code("A" * 128) == ()
    errors = validate_instrument_code("A" * 129)

    assert _fields(errors) == ["code"]
    assert errors[0].code is ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("DI1", "DI1"), ("di1", "DI1"), ("  Dol.Fut ", "DOL.FUT"), ("a_b/c-d", "A_B/C-D")],
)
def test_product_code_is_trimmed_and_upper_cased(typed: str, stored: str) -> None:
    # OQ-33 item 1: an instrument or product code is trimmed and upper-cased.
    assert validate_product_code(typed) == ()
    assert normalize_code(typed) == stored


@pytest.mark.parametrize(
    "typed",
    # Non-ASCII letters that upper-case into ASCII (U+FB01 → "FI", U+0131 → "I") are refused.
    ["", "   ", "DI 1", "DI1!", "DI1\x00", "A" * 33, "\ufb01", "d\u0131", "\u017f"],
)
def test_a_product_code_rejects_anything_else(typed: str) -> None:
    assert _fields(validate_product_code(typed)) == ["code"]


def test_a_product_code_fits_its_column_once_trimmed() -> None:
    assert validate_product_code(f" {'A' * 32} ") == ()
    assert normalize_code(f" {'A' * 32} ") == "A" * 32


def test_a_name_within_its_column_is_accepted() -> None:
    assert validate_name("Futuros", max_length=100) == ()


@pytest.mark.parametrize("name", ["A" * 101, "Fu\x00turos"])
def test_a_name_too_long_or_with_a_nul_is_rejected(name: str) -> None:
    assert _fields(validate_name(name, max_length=100)) == ["name"]


def test_a_blank_name_is_allowed_where_the_schema_allows_it() -> None:
    # Only products have a non-blank CHECK (schema.sql products_name_nonempty).
    assert validate_name("", max_length=100) == ()


@pytest.mark.parametrize("name", ["", "   "])
def test_a_non_blank_name_rejects_what_btrim_leaves_empty(name: str) -> None:
    assert _fields(validate_name(name, max_length=200, non_blank=True)) == ["name"]


def test_a_non_blank_name_counts_only_spaces_as_blank() -> None:
    assert validate_name("\u00a0", max_length=200, non_blank=True) == ()


def test_a_future_product_with_its_specification_is_valid() -> None:
    assert validate_futures_for_type("FUTURE", DI1_TERMS) == ()


def test_a_future_product_needs_a_specification() -> None:
    errors = validate_futures_for_type("FUTURE", None)

    assert _fields(errors) == ["futures"]
    assert errors[0].code is ErrorCode.VALIDATION_ERROR


def test_a_product_of_another_type_has_no_futures_specification() -> None:
    assert _fields(validate_futures_for_type("OPTION", DI1_TERMS)) == ["futures"]
    assert validate_futures_for_type("OPTION", None) == ()


@pytest.mark.parametrize(
    ("terms", "field"),
    [
        (
            FuturesTerms(Decimal("0"), Decimal("1"), "CASH", None),
            "futures.face_value",
        ),
        (
            FuturesTerms(Decimal("-100000"), Decimal("1"), "CASH", None),
            "futures.face_value",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("0"), "CASH", None),
            "futures.contract_multiplier",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("1"), "  ", None),
            "futures.settlement_method",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("1"), "C" * 33, None),
            "futures.settlement_method",
        ),
        (
            FuturesTerms(Decimal("Infinity"), Decimal("1"), "CASH", None),
            "futures.face_value",
        ),
        (
            FuturesTerms(Decimal("NaN"), Decimal("1"), "CASH", None),
            "futures.face_value",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("Infinity"), "CASH", None),
            "futures.contract_multiplier",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("sNaN"), "CASH", None),
            "futures.contract_multiplier",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("1"), "CA\x00SH", None),
            "futures.settlement_method",
        ),
        (
            FuturesTerms(Decimal("100000"), Decimal("1"), "CASH", "a\x00b"),
            "futures.settlement_description",
        ),
    ],
)
def test_the_futures_specification_respects_the_schema_checks(
    terms: FuturesTerms, field: str
) -> None:
    assert _fields(validate_futures_for_type("FUTURE", terms)) == [field]


def test_a_future_instrument_needs_a_maturity() -> None:
    assert validate_maturity("FUTURE", None) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe o vencimento.", "maturity_date"),
    )


@pytest.mark.parametrize("maturity", [date(2027, 1, 4), date(2020, 1, 2)])
def test_a_future_instrument_with_any_maturity_is_valid(maturity: date) -> None:
    # Maturities are exempt from the "nothing after today" rule and have no other bound.
    assert validate_maturity("FUTURE", maturity) == ()


def test_an_instrument_of_another_type_needs_no_maturity() -> None:
    assert validate_maturity("OPTION", None) == ()
