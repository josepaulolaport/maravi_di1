"""Prices' domain rules: what a typed reference price may be, and which observation is preferred
(spec §5; OQ-1, OQ-3, OQ-14, OQ-25). The typed quote's rules are Pricing's one validation
(code-review finding H3), run here on Pricing's field names, as the service does: the
validators return every problem, and the helper below raises them as one `DomainError`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.prices.application.services.price_service import validate_new_price
from di1.modules.prices.domain.reference_price import (
    PriceSource,
    ReferencePriceRecord,
    choose_preferred,
)
from di1.modules.pricing.public import Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

TODAY = date(2026, 10, 19)
MATURITY = date(2028, 1, 3)
MATURED_ON = date(2026, 10, 16)
"""A maturity on or before today, for the maturity-day cases."""


def _validate(
    reference_date: date = date(2026, 10, 16),
    input_kind: InputKind = InputKind.PU,
    pu: Decimal | None = Decimal("89250.3147019396"),
    rate: Decimal | None = None,
    maturity_date: date | None = MATURITY,
) -> Quote:
    errors = validate_new_price(
        today=TODAY,
        maturity_date=maturity_date,
        reference_date=reference_date,
        input_kind=input_kind,
        pu=pu,
        rate=rate,
    )
    if errors:
        raise DomainError(*errors)
    typed = pu if input_kind is InputKind.PU else rate
    assert typed is not None
    return Quote(input_kind, typed)


def _errors(excinfo: pytest.ExceptionInfo[DomainError]) -> tuple[ErrorDetail, ...]:
    return excinfo.value.errors


class TestValidReferencePrices:
    def test_a_typed_pu_is_the_quote(self) -> None:
        assert _validate() == Quote(InputKind.PU, Decimal("89250.3147019396"))

    def test_a_typed_rate_is_the_quote(self) -> None:
        quote = _validate(input_kind=InputKind.RATE, pu=None, rate=Decimal("0.0980"))

        assert quote == Quote(InputKind.RATE, Decimal("0.0980"))

    def test_today_is_accepted(self) -> None:
        assert _validate(reference_date=TODAY).kind is InputKind.PU

    def test_a_weekend_is_accepted(self) -> None:
        # 17/10/2026 is a Saturday: any calendar date is valid (OQ-7).
        assert _validate(reference_date=date(2026, 10, 17)).kind is InputKind.PU

    def test_the_maturity_date_accepts_a_typed_pu(self) -> None:
        quote = _validate(reference_date=MATURED_ON, pu=Decimal("100000"), maturity_date=MATURED_ON)

        assert quote == Quote(InputKind.PU, Decimal("100000"))

    def test_a_future_maturity_is_not_a_future_date(self) -> None:
        # Only the reference date is checked against today; the maturity is exempt (OQ-14).
        assert _validate(maturity_date=date(2035, 1, 2)).kind is InputKind.PU

    def test_the_largest_typed_precision_is_accepted(self) -> None:
        assert _validate(pu=Decimal("89250.3147019396")).value == Decimal("89250.3147019396")
        quote = _validate(input_kind=InputKind.RATE, pu=None, rate=Decimal("0.098000000001"))
        assert quote.value == Decimal("0.098000000001")

    def test_a_rate_just_above_minus_one_is_accepted(self) -> None:
        quote = _validate(input_kind=InputKind.RATE, pu=None, rate=Decimal("-0.999999999999"))

        assert quote.value == Decimal("-0.999999999999")


class TestRejectedDates:
    def test_a_date_after_today_is_a_future_date(self) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(reference_date=date(2026, 10, 20))

        assert _errors(excinfo) == (
            ErrorDetail(
                ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "reference_date"
            ),
        )

    def test_a_date_after_maturity_is_rejected(self) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(reference_date=date(2026, 10, 16), maturity_date=date(2026, 10, 15))

        assert _errors(excinfo) == (
            ErrorDetail(
                ErrorCode.CONTRACT_MATURED,
                "O contrato já venceu nesta data.",
                "reference_date",
            ),
        )

    def test_a_typed_rate_on_the_maturity_date_is_rejected(self) -> None:
        # On the maturity date the PU is typed and the rate is 0 (OQ-1).
        with pytest.raises(DomainError) as excinfo:
            _validate(
                reference_date=MATURED_ON,
                input_kind=InputKind.RATE,
                pu=None,
                rate=Decimal("0.1"),
                maturity_date=MATURED_ON,
            )

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Na data de vencimento informe o PU.", "rate"),
        )

    @pytest.mark.parametrize("rate", [None, Decimal("0.1234567890123"), Decimal("-2")])
    def test_on_the_maturity_date_a_rate_request_gets_one_message_on_rate(
        self, rate: Decimal | None
    ) -> None:
        # The rate is not typed on that date at all, so its missing or invalid value is not
        # reported next to "informe o PU", which would contradict it (CodeRabbit on #65).
        with pytest.raises(DomainError) as excinfo:
            _validate(
                reference_date=MATURED_ON,
                input_kind=InputKind.RATE,
                pu=None,
                rate=rate,
                maturity_date=MATURED_ON,
            )

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Na data de vencimento informe o PU.", "rate"),
        )

    def test_on_the_maturity_date_a_rate_request_with_a_pu_gets_only_the_maturity_message(
        self,
    ) -> None:
        # "Informe apenas a taxa, sem o PU." would tell the user the opposite of "informe o PU".
        with pytest.raises(DomainError) as excinfo:
            _validate(
                reference_date=MATURED_ON,
                input_kind=InputKind.RATE,
                pu=Decimal("100000"),
                rate=None,
                maturity_date=MATURED_ON,
            )

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Na data de vencimento informe o PU.", "rate"),
        )


class TestRejectedValues:
    @pytest.mark.parametrize(
        ("input_kind", "pu", "rate", "expected"),
        [
            (
                InputKind.PU,
                None,
                None,
                ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe o PU.", "pu"),
            ),
            (
                InputKind.RATE,
                None,
                None,
                ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe a taxa.", "rate"),
            ),
            (
                InputKind.PU,
                Decimal("89000"),
                Decimal("0.1"),
                ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe apenas o PU, sem a taxa.", "rate"),
            ),
            (
                InputKind.RATE,
                Decimal("89000"),
                Decimal("0.1"),
                ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe apenas a taxa, sem o PU.", "pu"),
            ),
        ],
    )
    def test_exactly_the_typed_value_is_given(
        self,
        input_kind: InputKind,
        pu: Decimal | None,
        rate: Decimal | None,
        expected: ErrorDetail,
    ) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(input_kind=input_kind, pu=pu, rate=rate)

        assert _errors(excinfo) == (expected,)

    def test_a_pu_with_more_than_10_places_is_rejected_not_rounded(self) -> None:
        # Trailing zeros were typed, so they count (OQ-3).
        with pytest.raises(DomainError) as excinfo:
            _validate(pu=Decimal("89250.31470193960"))

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use no máximo 10 casas decimais.", "pu"),
        )

    def test_a_rate_with_more_than_12_places_is_rejected_not_rounded(self) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(input_kind=InputKind.RATE, pu=None, rate=Decimal("0.0980000000001"))

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use no máximo 12 casas decimais.", "rate"),
        )

    @pytest.mark.parametrize("pu", [Decimal("0"), Decimal("-1"), Decimal("0.0000000000")])
    def test_a_pu_must_be_positive(self, pu: Decimal) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(pu=pu)

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "O PU deve ser maior que zero.", "pu"),
        )

    @pytest.mark.parametrize("rate", [Decimal("-1"), Decimal("-1.5")])
    def test_a_rate_must_be_above_minus_one(self, rate: Decimal) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(input_kind=InputKind.RATE, pu=None, rate=rate)

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "A taxa deve ser maior que −100%.", "rate"),
        )

    @pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
    def test_a_value_that_is_not_finite_is_rejected(self, value: Decimal) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(pu=value)

        assert _errors(excinfo) == (
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Informe um número válido.", "pu"),
        )

    def test_every_problem_is_reported_at_once(self) -> None:
        with pytest.raises(DomainError) as excinfo:
            _validate(reference_date=date(2026, 10, 20), pu=Decimal("-5"))

        assert {(e.code, e.field) for e in _errors(excinfo)} == {
            (ErrorCode.FUTURE_DATE, "reference_date"),
            (ErrorCode.VALIDATION_ERROR, "pu"),
        }


def _observation(source: PriceSource) -> ReferencePriceRecord:
    stamp = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
    return ReferencePriceRecord(
        id=uuid4(),
        asset_id=ASSET,
        reference_date=date(2026, 10, 16),
        source=source,
        input_kind=InputKind.PU,
        pu=Decimal("89250.3147019396"),
        rate=Decimal("0.098000000000"),
        created_at=stamp,
        updated_at=stamp,
    )


ASSET = uuid4()


class TestPreferredObservation:
    def test_manual_wins_over_b3(self) -> None:
        manual, b3 = _observation(PriceSource.MANUAL), _observation(PriceSource.B3)

        assert choose_preferred([b3, manual]) is manual
        assert choose_preferred([manual, b3]) is manual

    def test_b3_is_preferred_when_there_is_no_manual(self) -> None:
        b3 = _observation(PriceSource.B3)

        assert choose_preferred([b3]) is b3

    def test_no_observation_means_no_price(self) -> None:
        assert choose_preferred([]) is None
