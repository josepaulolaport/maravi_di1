"""Validation of a new ledger entry, before anything is priced or stored.

Rules: spec §6, §6.1, §6.2, §4.1; OQ-1 (maturity), OQ-3 (typed decimals rejected, never rounded),
OQ-13/OQ-24 (time required, one entry type per row), OQ-14 (nothing after today; bounds are only
the schema's CHECKs: rate > −1, PU > 0, quantity ≠ 0, amount ≠ 0, plus the column ranges
INTEGER and NUMERIC(20,2)). All the input errors are reported together; maturity is checked once
the input is well formed.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.ledger.domain.entries import (
    EntryDraft,
    EntryType,
    KnownInstrument,
    NewCashMovement,
    NewTrade,
    validate_cash_movement,
    validate_trade,
)
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind

TODAY = date(2026, 10, 18)
ASSET = UUID("6f1c2a10-0000-4000-8000-0000000000f8")
DI1F28 = KnownInstrument(maturity_date=date(2028, 1, 3))


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


def _errors(error: pytest.ExceptionInfo[DomainError]) -> set[tuple[ErrorCode, str | None]]:
    return {(detail.code, detail.field) for detail in error.value.errors}


# --- trades -------------------------------------------------------------------------------------


def test_a_rate_typed_trade_keeps_the_typed_rate() -> None:
    trade = validate_trade(_trade(), today=TODAY, instrument=DI1F28)

    assert trade == NewTrade(
        asset_id=ASSET,
        entry_date=date(2026, 10, 14),
        entry_time=time(14, 10),
        signed_quantity=10,
        input_kind=InputKind.RATE,
        typed_value=Decimal("0.10"),
    )
    assert str(trade.typed_value) == "0.10"  # as typed, trailing zero kept (OQ-3)


def test_a_pu_typed_sell_is_negative() -> None:
    trade = validate_trade(
        _trade(
            signed_quantity=-4,
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("82057.00"),
        ),
        today=TODAY,
        instrument=DI1F28,
    )

    assert trade.signed_quantity == -4
    assert trade.input_kind is InputKind.PU
    assert str(trade.typed_value) == "82057.00"


def test_today_and_weekends_are_accepted() -> None:
    saturday = date(2026, 10, 17)
    assert validate_trade(_trade(entry_date=TODAY), today=TODAY, instrument=DI1F28)
    assert validate_trade(_trade(entry_date=saturday), today=TODAY, instrument=DI1F28)


def test_a_trade_after_today_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(entry_date=date(2026, 10, 19)), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.FUTURE_DATE, "date")}
    assert error.value.errors[0].message == "A data não pode ser posterior a hoje."


def test_an_unknown_or_missing_contract_is_a_validation_error_on_asset_id() -> None:
    with pytest.raises(DomainError) as unknown:
        validate_trade(_trade(), today=TODAY, instrument=None)
    with pytest.raises(DomainError) as missing:
        validate_trade(_trade(asset_id=None), today=TODAY, instrument=None)

    assert _errors(unknown) == {(ErrorCode.VALIDATION_ERROR, "asset_id")}
    assert _errors(missing) == {(ErrorCode.VALIDATION_ERROR, "asset_id")}


@pytest.mark.parametrize("quantity", [None, 0, 2**31, -(2**31) - 1])
def test_the_quantity_is_a_nonzero_integer_within_the_column(quantity: int | None) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(signed_quantity=quantity), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "signed_quantity")}


@pytest.mark.parametrize("quantity", [2**31 - 1, -(2**31)])
def test_the_integer_column_limits_are_accepted(quantity: int) -> None:
    trade = validate_trade(_trade(signed_quantity=quantity), today=TODAY, instrument=DI1F28)
    assert trade.signed_quantity == quantity


def test_the_input_kind_is_required() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(input_kind=None, execution_rate=None), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "input_kind")}


def test_the_typed_value_of_the_input_kind_is_required() -> None:
    with pytest.raises(DomainError) as no_rate:
        validate_trade(_trade(execution_rate=None), today=TODAY, instrument=DI1F28)
    with pytest.raises(DomainError) as no_pu:
        validate_trade(
            _trade(input_kind=InputKind.PU, execution_rate=None), today=TODAY, instrument=DI1F28
        )

    assert _errors(no_rate) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert _errors(no_pu) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_rate_or_pu_is_typed_never_both() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(execution_pu=Decimal("89006.4625467350")), today=TODAY, instrument=DI1F28
        )

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_a_typed_pu_with_more_than_10_places_is_rejected_not_rounded() -> None:
    typed = {"input_kind": InputKind.PU, "execution_rate": None}
    ten = validate_trade(
        _trade(**typed, execution_pu=Decimal("89006.4625467350")), today=TODAY, instrument=DI1F28
    )
    assert ten.typed_value == Decimal("89006.4625467350")

    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(**typed, execution_pu=Decimal("89006.46254673501")),
            today=TODAY,
            instrument=DI1F28,
        )
    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}
    assert error.value.errors[0].message == "Use no máximo 10 casas decimais."


def test_a_typed_rate_with_more_than_12_places_is_rejected_trailing_zeros_count() -> None:
    assert validate_trade(
        _trade(execution_rate=Decimal("0.100000000000")), today=TODAY, instrument=DI1F28
    )
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(execution_rate=Decimal("0.1000000000000")), today=TODAY, instrument=DI1F28
        )

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert error.value.errors[0].message == "Use no máximo 12 casas decimais."


@pytest.mark.parametrize("pu", ["0", "0.0000000000", "-1"])
def test_the_pu_must_be_positive(pu: str) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(input_kind=InputKind.PU, execution_rate=None, execution_pu=Decimal(pu)),
            today=TODAY,
            instrument=DI1F28,
        )

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_pu")}


def test_the_rate_must_be_greater_than_minus_one() -> None:
    assert validate_trade(
        _trade(execution_rate=Decimal("-0.999999999999")), today=TODAY, instrument=DI1F28
    )
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(execution_rate=Decimal("-1")), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_value_that_is_not_finite_is_rejected(value: str) -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(execution_rate=Decimal(value)), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}


def test_a_cash_amount_on_a_trade_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(cash_amount=Decimal("10.00")), today=TODAY, instrument=DI1F28)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_every_input_error_is_reported_at_once() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(
            _trade(entry_date=date(2026, 10, 20), signed_quantity=0, input_kind=None),
            today=TODAY,
            instrument=DI1F28,
        )

    assert _errors(error) == {
        (ErrorCode.FUTURE_DATE, "date"),
        (ErrorCode.VALIDATION_ERROR, "signed_quantity"),
        (ErrorCode.VALIDATION_ERROR, "input_kind"),
    }


# --- maturity (OQ-1) ----------------------------------------------------------------------------

MATURING = KnownInstrument(maturity_date=date(2026, 10, 16))


def test_a_trade_on_the_maturity_date_with_a_typed_pu_is_accepted() -> None:
    trade = validate_trade(
        _trade(
            entry_date=date(2026, 10, 16),
            input_kind=InputKind.PU,
            execution_rate=None,
            execution_pu=Decimal("100000"),
        ),
        today=TODAY,
        instrument=MATURING,
    )

    assert trade.entry_date == MATURING.maturity_date


def test_a_rate_typed_on_the_maturity_date_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_trade(_trade(entry_date=date(2026, 10, 16)), today=TODAY, instrument=MATURING)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "execution_rate")}
    assert error.value.errors[0].message == "Na data de vencimento informe o PU."


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

    assert _errors(error) == {(ErrorCode.CONTRACT_MATURED, "date")}
    assert error.value.errors[0].message == "O contrato já venceu nesta data."


def test_a_maturity_after_today_is_exempt_from_the_future_date_rule() -> None:
    assert DI1F28.maturity_date is not None and DI1F28.maturity_date > TODAY
    assert validate_trade(_trade(entry_date=TODAY), today=TODAY, instrument=DI1F28)


# --- cash movements -----------------------------------------------------------------------------


def test_a_deposit_is_positive_and_a_withdrawal_negative() -> None:
    deposit = validate_cash_movement(_cash(), today=TODAY)
    withdrawal = validate_cash_movement(_cash(cash_amount=Decimal("-50000.00")), today=TODAY)

    assert deposit == NewCashMovement(
        entry_date=date(2026, 10, 14), entry_time=time(9, 0), amount=Decimal("1500000.00")
    )
    assert withdrawal.amount == Decimal("-50000.00")


@pytest.mark.parametrize("amount", [None, "0", "0.00", "-0"])
def test_the_amount_is_required_and_never_zero(amount: str | None) -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(
            _cash(cash_amount=None if amount is None else Decimal(amount)), today=TODAY
        )

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_an_amount_with_more_than_2_places_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(cash_amount=Decimal("10.001")), today=TODAY)

    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}
    assert error.value.errors[0].message == "Use no máximo 2 casas decimais."


def test_the_amount_fits_numeric_20_2() -> None:
    largest = Decimal("999999999999999999.99")
    assert validate_cash_movement(_cash(cash_amount=largest), today=TODAY).amount == largest
    assert validate_cash_movement(_cash(cash_amount=-largest), today=TODAY).amount == -largest

    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(cash_amount=Decimal("1000000000000000000")), today=TODAY)
    assert _errors(error) == {(ErrorCode.VALIDATION_ERROR, "cash_amount")}


def test_a_cash_movement_after_today_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        validate_cash_movement(_cash(entry_date=date(2026, 10, 19)), today=TODAY)

    assert _errors(error) == {(ErrorCode.FUTURE_DATE, "date")}


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

    assert _errors(error) == {
        (ErrorCode.VALIDATION_ERROR, field)
        for field in ("asset_id", "signed_quantity", "input_kind", "execution_pu", "execution_rate")
    }


def test_the_validators_refuse_a_draft_of_the_other_type() -> None:
    with pytest.raises(ValueError, match="TRADE"):
        validate_trade(_cash(), today=TODAY, instrument=DI1F28)
    with pytest.raises(ValueError, match="CASH"):
        validate_cash_movement(_trade(), today=TODAY)
