"""`PricingService` over Asset's real `AssetReader` on PostgreSQL 16: the instrument's maturity and
face value come from the catalogue (interfaces "Pricing"; plan §4.B; spec §4.1, §15 D4).

The catalogue is lane A's seed (``tests/integration/asset/conftest.py``): DI1 with face value
100000 and DI1F27…DI1F30. Only what needs the real reader is here: the catalogue's maturity and face
value reach the calculator (a day off would change the PU), an absent id is NOT_FOUND, and a
non-DI1 row is refused. The calculator's rules (maturity, precision, bounds) are unit-tested in
tests/unit/pricing/futures/.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.pricing.dependencies import build_pricing_service
from di1.modules.pricing.public import InputKind, Price, PricingService, Quote
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.shared.errors import DomainError, ErrorCode
from tests.support.db import Di1Catalogue, Writer, seed_di1


@pytest.fixture
async def catalogue_and_session(
    migrated_database_url: str,
) -> AsyncIterator[tuple[Di1Catalogue, Writer, AsyncSession]]:
    engine = create_engine(Settings(database_url=SecretStr(migrated_database_url)))
    try:
        session_factory = create_session_factory(engine)
        catalogue = await seed_di1(session_factory)
        async with session_factory() as session:
            yield catalogue, Writer(session_factory), session
    finally:
        await engine.dispose()


def service_on(session: AsyncSession) -> PricingService:
    return build_pricing_service(build_asset_reader(session))


async def test_a_di1_contract_is_priced_from_the_catalogue(
    catalogue_and_session: tuple[Di1Catalogue, Writer, AsyncSession],
) -> None:
    catalogue, _, session = catalogue_and_session
    # DI1F28 matures on 03/01/2028: 365 calendar days from 03/01/2027, so 100000 / 1.1.
    price = await service_on(session).calculate(
        catalogue.instrument_ids["DI1F28"], date(2027, 1, 3), Quote(InputKind.RATE, Decimal("0.10"))
    )

    assert price == Price(
        pu=Decimal("90909.0909090909"), rate=Decimal("0.10"), input_kind=InputKind.RATE
    )


async def test_an_unknown_instrument_is_not_found(
    catalogue_and_session: tuple[Di1Catalogue, Writer, AsyncSession],
) -> None:
    _, _, session = catalogue_and_session

    with pytest.raises(DomainError) as caught:
        await service_on(session).calculate(
            uuid4(), date(2027, 1, 3), Quote(InputKind.RATE, Decimal("0.1"))
        )

    assert caught.value.code is ErrorCode.NOT_FOUND


async def test_an_instrument_that_is_not_a_future_is_refused(
    catalogue_and_session: tuple[Di1Catalogue, Writer, AsyncSession],
) -> None:
    _, write, session = catalogue_and_session
    option = await write.instrument_type("OPTION", "Opções")
    equity = await write.asset_class(option, "EQUITY_OPTION", "Opções de ações")
    product_id = await write.product(equity, "PETR", "Opção de PETR4", None)
    instrument_id = await write.instrument(product_id, "PETRA10", None)

    with pytest.raises(DomainError) as caught:
        await service_on(session).calculate(
            instrument_id, date(2027, 1, 3), Quote(InputKind.RATE, Decimal("0.1"))
        )

    assert (caught.value.code, caught.value.errors[0].field) == (
        ErrorCode.VALIDATION_ERROR,
        "asset_id",
    )
