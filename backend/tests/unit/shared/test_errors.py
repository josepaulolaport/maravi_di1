"""The error catalogue shared by every module (OQ-15; interfaces.md "Errors")."""

from __future__ import annotations

import pytest

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail


def test_the_catalogue_has_exactly_the_six_documented_codes() -> None:
    assert {code.value for code in ErrorCode} == {
        "VALIDATION_ERROR",
        "FUTURE_DATE",
        "CONTRACT_MATURED",
        "NOT_FOUND",
        "INVALID_RANGE",
        "JOB_NOT_CANCELLABLE",
    }


def test_a_code_serialises_as_its_english_name() -> None:
    assert str(ErrorCode.FUTURE_DATE) == "FUTURE_DATE"


def test_a_domain_error_carries_its_details_in_order() -> None:
    first = ErrorDetail(
        ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "trade_date"
    )
    second = ErrorDetail(ErrorCode.VALIDATION_ERROR, "Valor inválido.", "quantity")

    error = DomainError(first, second)

    assert error.errors == (first, second)
    assert error.code is ErrorCode.FUTURE_DATE


def test_the_detail_defaults_to_the_first_message() -> None:
    error = DomainError(ErrorDetail(ErrorCode.NOT_FOUND, "Operação não encontrada."))

    assert error.detail == "Operação não encontrada."
    assert str(error) == "Operação não encontrada."


def test_an_explicit_detail_is_kept() -> None:
    error = DomainError(
        ErrorDetail(ErrorCode.INVALID_RANGE, "A data inicial é posterior à final.", "start_date"),
        detail="Intervalo inválido.",
    )

    assert error.detail == "Intervalo inválido."


def test_a_field_is_optional() -> None:
    assert ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, "O processamento já terminou.").field is None


def test_a_domain_error_needs_at_least_one_detail() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DomainError()
