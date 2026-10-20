"""`PricingService.calculate(instrument_id, reference_date, quote) -> Price`: the service reads the
instrument through `AssetReader`, prices it with its maturity and face value, and refuses what the
calculator cannot price (pricing/public.py; interfaces "Pricing"; spec §4.1, §7.4; OQ-1, OQ-2,
OQ-3).

The calculator's own rules are tested in tests/unit/pricing/futures/test_di1.py and the quote's in
futures/test_quote_validation.py; here, only the service's own work: it reads the instrument, feeds
the calculator its maturity and face value (never its multiplier), passes the answer and any
refusal through on Pricing's field names, and refuses an unknown or non-DI1 instrument.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from di1.modules.asset.public import AssetReader, Instrument
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import InputKind, Price, PricingService, Quote
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from tests.support.builders import CHALLENGE_DI1F28
from tests.support.fakes import FakeAssetReader

ONE_YEAR_BEFORE = date(2027, 1, 1)  # 365 calendar days to DI1F28's maturity


def service_for(*instruments: Instrument) -> PricingService:
    reader: AssetReader = FakeAssetReader(*instruments)
    return build_pricing_service(reader)


def refusal(caught: pytest.ExceptionInfo[DomainError]) -> ErrorDetail:
    (detail,) = caught.value.errors
    return detail


RATE_10 = Quote(InputKind.RATE, Decimal("0.10"))


async def test_the_challenge_example_prices_from_the_instrument() -> None:
    # DI1F28 at 10% a.a. on 01/01/2027: 100000 / 1.1 (desafio §5; spec §15 D4).
    price = await service_for(CHALLENGE_DI1F28).calculate(
        CHALLENGE_DI1F28.id, ONE_YEAR_BEFORE, RATE_10
    )

    assert price == Price(
        pu=Decimal("90909.0909090909"), rate=Decimal("0.10"), input_kind=InputKind.RATE
    )


@pytest.mark.parametrize(
    ("instrument", "reference_date", "pu"),
    [
        # 1000 / 1.1 = 909.090909090909…
        pytest.param(
            replace(CHALLENGE_DI1F28, id=uuid4(), face_value=Decimal("1000")),
            ONE_YEAR_BEFORE,
            "909.0909090909",
            id="face-value",
        ),
        # 01/01/2029 → 01/01/2031: 730 days, no 29/02, so 100000 / 1.1^2 = 82644.62809917355371…
        pytest.param(
            replace(CHALLENGE_DI1F28, id=uuid4(), maturity_date=date(2031, 1, 1)),
            date(2029, 1, 1),
            "82644.6280991736",
            id="maturity-date",
        ),
        # OQ-2: stored on the product, never used by the formula.
        pytest.param(
            replace(CHALLENGE_DI1F28, id=uuid4(), multiplier=Decimal("10")),
            ONE_YEAR_BEFORE,
            "90909.0909090909",
            id="multiplier-not-applied",
        ),
        pytest.param(
            replace(CHALLENGE_DI1F28, id=uuid4(), product_code="di1"),
            ONE_YEAR_BEFORE,
            "90909.0909090909",
            id="product-code-any-case",
        ),
    ],
)
async def test_the_terms_come_from_the_instrument(
    instrument: Instrument, reference_date: date, pu: str
) -> None:
    price = await service_for(instrument).calculate(instrument.id, reference_date, RATE_10)

    assert price.pu == Decimal(pu)


async def test_a_calculator_refusal_passes_through_on_pricing_fields() -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(CHALLENGE_DI1F28).calculate(
            CHALLENGE_DI1F28.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.1000000000001"))
        )

    assert refusal(caught) == ErrorDetail(
        ErrorCode.VALIDATION_ERROR, "Use no máximo 12 casas decimais.", "rate"
    )


async def test_an_unknown_instrument_is_not_found() -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(CHALLENGE_DI1F28).calculate(uuid4(), ONE_YEAR_BEFORE, RATE_10)

    assert refusal(caught) == ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado.")


NOT_PRICEABLE = ErrorDetail(
    ErrorCode.VALIDATION_ERROR,
    "O contrato não pode ser precificado: só contratos futuros DI1 têm cálculo de PU e taxa.",
    "asset_id",
)


@pytest.mark.parametrize(
    "instrument",
    [
        replace(
            CHALLENGE_DI1F28,
            id=uuid4(),
            product_code="PETR",
            instrument_type="OPTION",
            asset_class="EQUITY_OPTION",
            maturity_date=None,
            face_value=None,
            multiplier=None,
            settlement_method=None,
        ),
        # Only DI1 has a calculator (spec §4.1: one product file, futures/di1.py).
        replace(CHALLENGE_DI1F28, id=uuid4(), code="DAPK28", product_code="DAP"),
        replace(CHALLENGE_DI1F28, id=uuid4(), maturity_date=None),
        replace(CHALLENGE_DI1F28, id=uuid4(), face_value=None),
    ],
    ids=["not-a-future", "another-product", "no-maturity", "no-face-value"],
)
async def test_an_instrument_without_di1_terms_is_refused(instrument: Instrument) -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(instrument).calculate(instrument.id, ONE_YEAR_BEFORE, RATE_10)

    assert refusal(caught) == NOT_PRICEABLE
