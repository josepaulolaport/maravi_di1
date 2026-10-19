"""The error catalogue shared by every module (OQ-15; interfaces.md "Errors")."""

from __future__ import annotations

import copy
import pickle

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


def test_several_details_leave_the_summary_to_the_http_layer() -> None:
    error = DomainError(
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Valor inválido.", "quantity"),
        ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "trade_date"),
    )

    assert error.detail is None
    assert str(error) == "Valor inválido.; A data não pode ser posterior a hoje."


def test_an_explicit_detail_is_kept() -> None:
    error = DomainError(
        ErrorDetail(ErrorCode.INVALID_RANGE, "A data inicial é posterior à final.", "start_date"),
        detail="Intervalo inválido.",
    )

    assert error.detail == "Intervalo inválido."


def test_validation_is_a_validation_error() -> None:
    assert ErrorDetail.validation("Valor inválido.", "quantity") == ErrorDetail(
        ErrorCode.VALIDATION_ERROR, "Valor inválido.", "quantity"
    )
    assert ErrorDetail.validation("JSON inválido.").field is None


def test_a_field_is_optional() -> None:
    assert ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, "O processamento já terminou.").field is None


def test_a_domain_error_needs_at_least_one_detail() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DomainError()


@pytest.mark.parametrize("detail", [None, "Intervalo inválido."])
def test_a_domain_error_survives_copy_and_pickle(detail: str | None) -> None:
    error = DomainError(
        ErrorDetail(ErrorCode.INVALID_RANGE, "A data inicial é posterior à final.", "start_date"),
        detail=detail,
    )

    for clone in (copy.copy(error), pickle.loads(pickle.dumps(error))):
        assert isinstance(clone, DomainError)
        assert clone.errors == error.errors
        assert clone.detail == error.detail
        assert str(clone) == str(error)
