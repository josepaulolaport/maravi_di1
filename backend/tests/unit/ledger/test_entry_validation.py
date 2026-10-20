"""Validation of a new ledger entry, before anything is priced or stored.

Rules: spec §6, §6.1, §6.2, §4.1; OQ-1 (maturity), OQ-3 (typed decimals rejected, never rounded),
OQ-13/OQ-24 (time required, one entry type per row), OQ-14 (nothing after today; bounds are only
the schema's CHECKs: rate > −1, PU > 0, quantity ≠ 0, amount ≠ 0, plus the column ranges
INTEGER and NUMERIC(20,2)). All the errors are reported together, the maturity's included.

The typed quote's rules are Pricing's one validation (code-review finding H3), which Ledger runs
on its request fields; these tests run it through Ledger's own binding. The validators return
every problem; like the service, the helpers below raise them as one `DomainError`.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.ledger.application.services.ledger_service import validate_new_trade
from di1.modules.ledger.domain import entries
from di1.modules.ledger.domain.entries import EntryDraft, EntryType, cash_description
from di1.shared.clock import SAO_PAULO
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind
from tests.support.http import errors_of

TODAY = date(2026, 10, 18)
ASSET = UUID("6f1c2a10-0000-4000-8000-0000000000f8")
DI1F28 = date(2028, 1, 3)


def validate_trade(draft: EntryDraft, *, today: date, instrument: date | None = DI1F28) -> None:
    errors = validate_new_trade(
        draft, today=today, maturity_date=instrument, known=instrument is not None
    )
    if errors:
        raise DomainError(*errors)


def validate_cash_movement(draft: EntryDraft, *, today: date) -> None:
    errors = entries.validate_cash_movement(draft, today=today)
    if errors:
        raise DomainError(*errors)


def _trade(**overrides: object) -> EntryDraft:
    fields: dict[str, object] = {
        "type": EntryType.TRADE,
        "entry_date": date(2026, 10, 14),
        "entry_time": time(14, 10),
        "asset_id": ASSET,
        "signed_quantity": 10,
        "input_kind": InputKind.RATE,
        "execution_rate": Decimal("0.10"),
    }
    fields.update(overrides)
    return EntryDraft(**fields)  # type: ignore[arg-type]


def _cash(**overrides: object) -> EntryDraft:
    fields: dict[str, object] = {
        "type": EntryType.CASH,
        "entry_date": date(2026, 10, 14),
        "entry_time": time(9, 0),
        "cash_amount": Decimal("1500000.00"),
    }
    fields.update(overrides)
    return EntryDraft(**fields)  # type: ignore[arg-type]


# --- trades -------------------------------------------------------------------------------------


def test_a_rate_typed_trade_is_accepted() -> None:
    validate_trade(_trade(), today=TODAY, instrument=DI1F28)


def test_a_pu_typed_sell_is_accepted() -> None:
    validate_trade(
        _trade(
            signed_quantity=-4,
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("82057.00"),
        ),
        today=TODAY,
        instrument=DI1F28,
    )


def test_today_and_weekends_are_accepted() -> None:
    saturday = date(2026, 10, 17)
    validate_trade(_trade(entry_date=TODAY), today=TODAY, instrument=DI1F28)
    validate_trade(_trade(entry_date=saturday), today=TODAY, instrument=DI1F28)


def test_a_trade_after_today_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(entry_date=date(2026, 10, 19)), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.FUTURE_DATE, "date")}
    assert error.value.errors[0].message == "A data não pode ser posterior a hoje."


def test_an_unknown_or_missing_contract_is_a_validation_error_on_asset_id() -> None:
    with pytest.raises(DomainError) as unknown:
        validate_trade(_trade(), today=TODAY, instrument=None)
    with pytest.raises(DomainError) as missing:
        validate_trade(_trade(asset_id=None), today=TODAY, instrument=None)

    assert set(errors_of(unknown)) == {(ErrorCode.VALIDATION_ERROR, "asset_id")}
    assert set(errors_of(missing)) == {(ErrorCode.VALIDATION_ERROR, "asset_id")}


@pytest.mark.parametrize("quantity", [None, 0, 2**31, -(2**31) - 1])
def test_the_quantity_is_a_nonzero_integer_within_the_column(quantity: int | None) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(signed_quantity=quantity), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "signed_quantity")}


@pytest.mark.parametrize("quantity", [2**31 - 1, -(2**31)])
def test_the_integer_column_limits_are_accepted(quantity: int) -> None:
    validate_trade(_trade(signed_quantity=quantity), today=TODAY, instrument=DI1F28)


def test_the_input_kind_is_required() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(input_kind=None, execution_rate=None), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "input_kind")}


def test_the_typed_value_of_the_input_kind_is_required() -> None:
    with pytest.raises(DomainError) as no_rate:
        validate_trade(_trade(execution_rate=None), today=TODAY, instrument=DI1F28)
    with pytest.raises(DomainError) as no_pu:
        validate_trade(
            _trade(input_kind=InputKind.PU, execution_rate=None), today=TODAY, instrument=DI1F28
        )

    assert set(errors_of(no_rate)) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert set(errors_of(no_pu)) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_rate_or_pu_is_typed_never_both() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(execution_pu=Decimal("89006.4625467350")), today=TODAY, instrument=DI1F28
        )

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_a_typed_pu_with_more_than_10_places_is_rejected_not_rounded() -> None:
    typed = {"input_kind": InputKind.PU, "execution_rate": None}
    validate_trade(
        _trade(**typed, execution_pu=Decimal("89006.4625467350")), today=TODAY, instrument=DI1F28
    )

    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(**typed, execution_pu=Decimal("89006.46254673501")),
            today=TODAY,
            instrument=DI1F28,
        )
    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}
    assert error.value.errors[0].message == "Use no máximo 10 casas decimais."


def test_a_typed_rate_with_more_than_12_places_is_rejected_trailing_zeros_count() -> None:
    validate_trade(_trade(execution_rate=Decimal("0.100000000000")), today=TODAY, instrument=DI1F28)
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(execution_rate=Decimal("0.1000000000000")), today=TODAY, instrument=DI1F28
        )

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert error.value.errors[0].message == "Use no máximo 12 casas decimais."


@pytest.mark.parametrize("pu", ["0", "0.0000000000", "-1"])
def test_the_pu_must_be_positive(pu: str) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(input_kind=InputKind.PU, execution_rate=None, execution_pu=Decimal(pu)),
            today=TODAY,
            instrument=DI1F28,
        )

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_the_rate_must_be_greater_than_minus_one() -> None:
    validate_trade(
        _trade(execution_rate=Decimal("-0.999999999999")), today=TODAY, instrument=DI1F28
    )
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(execution_rate=Decimal("-1")), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_value_that_is_not_finite_is_rejected(value: str) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(execution_rate=Decimal(value)), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}


def test_a_cash_amount_on_a_trade_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(cash_amount=Decimal("10.00")), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_every_input_error_is_reported_at_once() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(entry_date=date(2026, 10, 20), signed_quantity=0, input_kind=None),
            today=TODAY,
            instrument=DI1F28,
        )

    assert set(errors_of(error)) == {
        (ErrorCode.FUTURE_DATE, "date"),
        (ErrorCode.VALIDATION_ERROR, "signed_quantity"),
        (ErrorCode.VALIDATION_ERROR, "input_kind"),
    }


@pytest.mark.parametrize(
    "entry_time",
    [time(14, 10, 0, 500_000), time(14, 10, tzinfo=SAO_PAULO)],
    ids=["fractions", "aware"],
)
def test_the_time_is_a_naive_whole_second(entry_time: time) -> None:
    # The keyset cursor carries HH:MM:SS (OQ-26 item 1): a stored fraction or offset would make
    # pages skip or repeat entries, whoever the writer is.
    for draft in (_trade(entry_time=entry_time), _cash(entry_time=entry_time)):
        with pytest.raises(DomainError) as error:
            if draft.type is EntryType.TRADE:
                validate_trade(draft, today=TODAY, instrument=DI1F28)
            else:
                validate_cash_movement(draft, today=TODAY)

        assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "time")}


# --- maturity (OQ-1) ----------------------------------------------------------------------------

MATURING = date(2026, 10, 16)


def test_a_trade_on_the_maturity_date_with_a_typed_pu_is_accepted() -> None:
    validate_trade(
        _trade(
            entry_date=date(2026, 10, 16),
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("100000"),
        ),
        today=TODAY,
        instrument=MATURING,
    )


def test_a_rate_typed_on_the_maturity_date_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(entry_date=date(2026, 10, 16)), today=TODAY, instrument=MATURING)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert error.value.errors[0].message == "Na data de vencimento informe o PU."


@pytest.mark.parametrize("execution_rate", [None, Decimal("0.1234567890123"), Decimal("-2")])
def test_on_the_maturity_date_a_rate_trade_gets_one_message_on_the_rate(
    execution_rate: Decimal | None,
) -> None:
    # The rate is not typed on that date at all: a missing or invalid rate is not reported next
    # to "informe o PU", which would contradict it.
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(entry_date=date(2026, 10, 16), execution_rate=execution_rate),
            today=TODAY,
            instrument=MATURING,
        )

    assert [(e.code, e.message, e.field) for e in error.value.errors] == [
        (ErrorCode.VALIDATION_ERROR, "Na data de vencimento informe o PU.", "execution_rate")
    ]


def test_a_matured_date_is_reported_with_the_other_input_errors() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(entry_date=date(2026, 10, 17), signed_quantity=0),
            today=TODAY,
            instrument=MATURING,
        )

    assert set(errors_of(error)) == {
        (ErrorCode.CONTRACT_MATURED, "date"),
        (ErrorCode.VALIDATION_ERROR, "signed_quantity"),
    }


def test_a_trade_after_the_maturity_date_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(
                entry_date=date(2026, 10, 17),
                input_kind=InputKind.PU,
                execution_rate=None,
                execution_pu=Decimal("100000"),
            ),
            today=TODAY,
            instrument=MATURING,
        )

    assert set(errors_of(error)) == {(ErrorCode.CONTRACT_MATURED, "date")}
    assert error.value.errors[0].message == "O contrato já venceu nesta data."


def test_a_maturity_after_today_is_exempt_from_the_future_date_rule() -> None:
    assert DI1F28 > TODAY
    validate_trade(_trade(entry_date=TODAY), today=TODAY, instrument=DI1F28)


# --- cash movements -----------------------------------------------------------------------------


def test_a_positive_deposit_and_a_negative_withdrawal_are_accepted() -> None:
    # The signed amount is stored as given (test_ledger_service, test_ledger_persistence).
    assert entries.validate_cash_movement(_cash(), today=TODAY) == ()
    withdrawal = _cash(cash_amount=Decimal("-50000.00"))
    assert entries.validate_cash_movement(withdrawal, today=TODAY) == ()


@pytest.mark.parametrize("amount", [None, "0", "0.00", "-0"])
def test_the_amount_is_required_and_never_zero(amount: str | None) -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(
            _cash(cash_amount=None if amount is None else Decimal(amount)), today=TODAY
        )

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_an_amount_with_more_than_2_places_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(cash_amount=Decimal("10.001")), today=TODAY)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}
    assert error.value.errors[0].message == "Use no máximo 2 casas decimais."


def test_the_amount_fits_numeric_20_2() -> None:
    largest = Decimal("999999999999999999.99")
    validate_cash_movement(_cash(cash_amount=largest), today=TODAY)
    validate_cash_movement(_cash(cash_amount=-largest), today=TODAY)

    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(cash_amount=Decimal("1000000000000000000")), today=TODAY)
    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_a_cash_movement_after_today_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(entry_date=date(2026, 10, 19)), today=TODAY)

    assert set(errors_of(error)) == {(ErrorCode.FUTURE_DATE, "date")}


def test_trade_fields_on_a_cash_movement_are_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(
            _cash(
                asset_id=ASSET,
                signed_quantity=1,
                input_kind=InputKind.PU,
                execution_pu=Decimal("1"),
                execution_rate=Decimal("0.1"),
            ),
            today=TODAY,
        )

    assert set(errors_of(error)) == {
        (ErrorCode.VALIDATION_ERROR, field)
        for field in ("asset_id", "signed_quantity", "input_kind", "execution_pu", "execution_rate")
    }


# --- cash description (OQ-51) -------------------------------------------------------------------


def test_a_cash_movement_keeps_its_description_trimmed() -> None:
    draft = _cash(description="  Aporte inicial \n")

    assert entries.validate_cash_movement(draft, today=TODAY) == ()
    assert cash_description(draft) == "Aporte inicial"


def test_a_description_is_stored_composed() -> None:
    # The list's SQL search folds precomposed letters (OQ-51): "a" + U+0301 is stored as "á".
    assert cash_description(_cash(description="Aplicac\u0327a\u0303o")) == "Aplicação"


@pytest.mark.parametrize("description", [None, "", "   ", "\t\n"])
def test_an_absent_or_blank_description_is_none(description: str | None) -> None:
    assert cash_description(_cash(description=description)) is None


def test_a_description_of_200_characters_is_accepted() -> None:
    draft = _cash(description=f" {'á' * 200} ")

    assert entries.validate_cash_movement(draft, today=TODAY) == ()
    assert cash_description(draft) == "á" * 200


def test_a_description_longer_than_200_characters_is_rejected_not_cut() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(description="a" * 201), today=TODAY)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "description")}
    assert error.value.errors[0].message == "A descrição deve ter no máximo 200 caracteres."


def test_a_long_description_is_reported_with_the_other_input_errors() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(cash_amount=None, description="a" * 201), today=TODAY)

    assert set(errors_of(error)) == {
        (ErrorCode.VALIDATION_ERROR, "cash_amount"),
        (ErrorCode.VALIDATION_ERROR, "description"),
    }


def test_a_description_with_a_nul_character_is_rejected() -> None:
    # PostgreSQL text cannot hold NUL (OQ-15): a 422, never a database error.
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(description="a\x00b"), today=TODAY)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "description")}
    assert error.value.errors[0].message == "O texto não pode conter o caractere nulo."


@pytest.mark.parametrize("description", ["Compra", " Compra "])
def test_a_trade_takes_no_description(description: str) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(description=description), today=TODAY, instrument=DI1F28)

    assert set(errors_of(error)) == {(ErrorCode.VALIDATION_ERROR, "description")}
    assert error.value.errors[0].message == "Uma operação não tem descrição."


@pytest.mark.parametrize("description", [None, "", "   "])
def test_a_blank_description_on_a_trade_is_no_description(description: str | None) -> None:
    # Trimmed first, as on a cash entry: blank is absent (OQ-51 item 1).
    validate_trade(_trade(description=description), today=TODAY, instrument=DI1F28)


def test_the_validators_refuse_a_draft_of_the_other_type() -> None:
    with pytest.raises(ValueError, match="TRADE"):
        validate_trade(_cash(), today=TODAY, instrument=DI1F28)
    with pytest.raises(ValueError, match="CASH"):
        validate_cash_movement(_trade(), today=TODAY)
