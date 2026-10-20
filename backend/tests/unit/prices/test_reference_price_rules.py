"""Prices' domain rules: the date of a typed reference price, which observation is preferred,
and how one asset's observations become its days (spec §5; OQ-7, OQ-14, OQ-25).

The typed quote itself (presence, decimals, bounds, maturity; OQ-1, OQ-3, OQ-14) is Pricing's one
validation (code-review finding H3), tested in ``tests/unit/pricing/futures/
test_quote_validation.py`` on the same field names Prices uses; here only its composition with
the date rule is tested."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.prices.application.services.price_service import validate_new_price
from di1.modules.prices.domain.reference_price import (
    PriceSource,
    ReferencePriceDay,
    ReferencePriceRecord,
    choose_preferred,
    reference_days,
)
from di1.shared.errors import ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

TODAY = date(2026, 10, 19)
MATURITY = date(2028, 1, 3)
ASSET = uuid4()
FUTURE_DATE = ErrorDetail(
    ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "reference_date"
)


def _problems(
    reference_date: date = date(2026, 10, 16),
    input_kind: InputKind = InputKind.PU,
    pu: Decimal | None = Decimal("89250.3147019396"),
    rate: Decimal | None = None,
    maturity_date: date | None = MATURITY,
) -> tuple[ErrorDetail, ...]:
    return validate_new_price(
        today=TODAY,
        maturity_date=maturity_date,
        reference_date=reference_date,
        input_kind=input_kind,
        pu=pu,
        rate=rate,
    )


# --- the date (OQ-7, OQ-14) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference_date", "maturity_date"),
    [
        pytest.param(TODAY, MATURITY, id="today"),
        # 17/10/2026 is a Saturday: any calendar date is valid (OQ-7).
        pytest.param(date(2026, 10, 17), MATURITY, id="weekend"),
        # Only the reference date is checked against today; the maturity is exempt (OQ-14).
        pytest.param(date(2026, 10, 16), date(2035, 1, 2), id="far-maturity"),
    ],
)
def test_a_date_up_to_today_is_accepted(reference_date: date, maturity_date: date) -> None:
    assert _problems(reference_date=reference_date, maturity_date=maturity_date) == ()


def test_a_date_after_today_is_a_future_date() -> None:
    assert _problems(reference_date=date(2026, 10, 20)) == (FUTURE_DATE,)


# --- composed with Pricing's quote validation ------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        pytest.param(
            {"reference_date": date(2026, 10, 16), "maturity_date": date(2026, 10, 15)},
            ErrorDetail(
                ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "reference_date"
            ),
            id="after-maturity",
        ),
        pytest.param(
            # On the maturity date the PU is typed and the rate is 0 (OQ-1).
            {
                "reference_date": date(2026, 10, 16),
                "maturity_date": date(2026, 10, 16),
                "input_kind": InputKind.RATE,
                "pu": None,
                "rate": Decimal("0.1"),
            },
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Na data de vencimento informe o PU.", "rate"),
            id="rate-on-maturity-day",
        ),
        pytest.param(
            {"pu": Decimal("89250.31470193960")},
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use no máximo 10 casas decimais.", "pu"),
            id="pu-decimals",
        ),
    ],
)
def test_the_quote_problems_come_on_the_request_fields(
    price: dict[str, object], expected: ErrorDetail
) -> None:
    assert _problems(**price) == (expected,)  # type: ignore[arg-type]


def test_the_maturity_date_accepts_a_typed_pu() -> None:
    on_maturity = date(2026, 10, 16)

    assert (
        _problems(reference_date=on_maturity, pu=Decimal("100000"), maturity_date=on_maturity) == ()
    )


def test_every_problem_is_reported_at_once() -> None:
    assert _problems(reference_date=date(2026, 10, 20), pu=Decimal("-5")) == (
        FUTURE_DATE,
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "O PU deve ser maior que zero.", "pu"),
    )


# --- the preferred observation (spec §5) -----------------------------------------------------


def _observation(source: PriceSource, day: date = date(2026, 10, 16)) -> ReferencePriceRecord:
    stamp = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
    return ReferencePriceRecord(
        id=uuid4(),
        asset_id=ASSET,
        reference_date=day,
        source=source,
        input_kind=InputKind.PU,
        pu=Decimal("89250.3147019396"),
        rate=Decimal("0.098000000000"),
        created_at=stamp,
        updated_at=stamp,
    )


def test_manual_wins_over_b3() -> None:
    manual, b3 = _observation(PriceSource.MANUAL), _observation(PriceSource.B3)

    assert choose_preferred([b3, manual]) is manual
    assert choose_preferred([manual, b3]) is manual


def test_b3_is_preferred_when_there_is_no_manual() -> None:
    b3 = _observation(PriceSource.B3)

    assert choose_preferred([b3]) is b3


def test_no_observation_means_no_price() -> None:
    assert choose_preferred([]) is None


# --- an asset's days ---------------------------------------------------------------------------


def test_days_come_newest_first_with_the_preferred_source_first() -> None:
    older = _observation(PriceSource.B3, date(2026, 10, 14))
    b3 = _observation(PriceSource.B3)
    manual = _observation(PriceSource.MANUAL)

    assert reference_days([older, b3, manual]) == [
        ReferencePriceDay(date(2026, 10, 16), manual, (manual, b3)),
        ReferencePriceDay(date(2026, 10, 14), older, (older,)),
    ]


def test_no_observation_means_no_day() -> None:
    assert reference_days([]) == []
