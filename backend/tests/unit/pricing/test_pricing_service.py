"""`PricingService.calculate(instrument_id, reference_date, quote) -> Price`: the service reads the
instrument through `AssetReader`, prices it with its maturity and face value, and refuses what the
calculator cannot price (pricing/public.py; interfaces "Pricing"; spec §4.1, §7.4; OQ-1, OQ-2,
OQ-3).

The calculator's own rules are tested in tests/unit/pricing/futures/test_di1.py; here, only that
the service feeds it the instrument's facts and passes its answers and refusals through.
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


async def test_the_challenge_example_prices_from_the_instrument() -> None:
    # DI1F28 at 10% a.a. on 01/01/2027: 100000 / 1.1 (desafio §5; spec §15 D4).
    price = await service_for(CHALLENGE_DI1F28).calculate(
        CHALLENGE_DI1F28.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price == Price(
        pu=Decimal("90909.0909090909"), rate=Decimal("0.10"), input_kind=InputKind.RATE
    )


async def test_a_typed_pu_gives_the_rate() -> None:
    price = await service_for(CHALLENGE_DI1F28).calculate(
        CHALLENGE_DI1F28.id, ONE_YEAR_BEFORE, Quote(InputKind.PU, Decimal("90909.0909090909"))
    )

    assert price == Price(
        pu=Decimal("90909.0909090909"), rate=Decimal("0.100000000000"), input_kind=InputKind.PU
    )


async def test_the_face_value_comes_from_the_instrument() -> None:
    # 1000 / 1.1 = 909.090909090909…
    small = replace(CHALLENGE_DI1F28, id=uuid4(), face_value=Decimal("1000"))

    price = await service_for(small).calculate(
        small.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price.pu == Decimal("909.0909090909")


async def test_the_maturity_comes_from_the_instrument() -> None:
    # 01/01/2029 → 01/01/2031: 730 days, no 29/02, so 100000 / 1.1^2 = 82644.62809917355371…
    longer = replace(CHALLENGE_DI1F28, id=uuid4(), maturity_date=date(2031, 1, 1))

    price = await service_for(longer).calculate(
        longer.id, date(2029, 1, 1), Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price.pu == Decimal("82644.6280991736")


async def test_the_multiplier_is_not_applied() -> None:
    # OQ-2: stored on the product, never used by the formula.
    tenfold = replace(CHALLENGE_DI1F28, id=uuid4(), multiplier=Decimal("10"))

    price = await service_for(tenfold).calculate(
        tenfold.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price.pu == Decimal("90909.0909090909")


async def test_the_product_code_is_case_insensitive() -> None:
    lower = replace(CHALLENGE_DI1F28, id=uuid4(), product_code="di1")

    price = await service_for(lower).calculate(
        lower.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price.pu == Decimal("90909.0909090909")


async def test_on_the_maturity_date_the_pu_is_typed_and_the_rate_is_zero() -> None:
    price = await service_for(CHALLENGE_DI1F28).calculate(
        CHALLENGE_DI1F28.id, date(2028, 1, 1), Quote(InputKind.PU, Decimal("99990.12"))
    )

    assert price == Price(
        pu=Decimal("99990.12"), rate=Decimal("0.000000000000"), input_kind=InputKind.PU
    )


async def test_after_the_maturity_date_the_contract_is_matured() -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(CHALLENGE_DI1F28).calculate(
            CHALLENGE_DI1F28.id, date(2028, 1, 2), Quote(InputKind.PU, Decimal("99990"))
        )

    assert refusal(caught).code is ErrorCode.CONTRACT_MATURED


async def test_a_typed_value_with_too_many_decimals_is_rejected() -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(CHALLENGE_DI1F28).calculate(
            CHALLENGE_DI1F28.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.1000000000001"))
        )

    assert refusal(caught) == ErrorDetail(
        ErrorCode.VALIDATION_ERROR, "Use no máximo 12 casas decimais.", "rate"
    )


async def test_an_unknown_instrument_is_not_found() -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(CHALLENGE_DI1F28).calculate(
            uuid4(), ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
        )

    assert refusal(caught) == ErrorDetail(ErrorCode.NOT_FOUND, "Contrato não encontrado.")


NOT_PRICEABLE = ErrorDetail(
    ErrorCode.VALIDATION_ERROR,
    "O contrato não pode ser precificado: só contratos futuros DI1 têm cálculo de PU e taxa.",
    "asset_id",
)


async def test_an_instrument_that_is_not_a_future_is_refused() -> None:
    option = replace(
        CHALLENGE_DI1F28,
        id=uuid4(),
        product_code="PETR",
        instrument_type="OPTION",
        asset_class="EQUITY_OPTION",
        maturity_date=None,
        face_value=None,
        multiplier=None,
        settlement_method=None,
    )

    with pytest.raises(DomainError) as caught:
        await service_for(option).calculate(
            option.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
        )

    assert refusal(caught) == NOT_PRICEABLE


async def test_a_future_of_another_product_is_refused() -> None:
    # Only DI1 has a calculator (spec §4.1: one product file, futures/di1.py).
    dap = replace(CHALLENGE_DI1F28, id=uuid4(), code="DAPK28", product_code="DAP")

    with pytest.raises(DomainError) as caught:
        await service_for(dap).calculate(
            dap.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
        )

    assert refusal(caught) == NOT_PRICEABLE


@pytest.mark.parametrize(
    "incomplete",
    [
        replace(CHALLENGE_DI1F28, id=uuid4(), maturity_date=None),
        replace(CHALLENGE_DI1F28, id=uuid4(), face_value=None),
    ],
    ids=["no_maturity", "no_face_value"],
)
async def test_a_di1_instrument_without_its_terms_is_refused(
    incomplete: Instrument,
) -> None:
    with pytest.raises(DomainError) as caught:
        await service_for(incomplete).calculate(
            incomplete.id, ONE_YEAR_BEFORE, Quote(InputKind.RATE, Decimal("0.10"))
        )

    assert refusal(caught) == NOT_PRICEABLE
