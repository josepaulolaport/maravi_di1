"""`PriceService` with the real Asset reader and Pricing service on PostgreSQL: the stored PU ↔ rate
pair is the DC/365 one (spec §4.1; OQ-1, OQ-3).

Expected values are those of the frontend demo fixtures (``frontend/src/api/mocks/fixtures.ts``,
DI1F28 maturing 03/01/2028), recomputed independently with ``decimal`` at 34 digits, half-up:
0.0980 on 16/10/2026 (444 days) is PU 89250.3147019396, and that PU gives back 0.098000000000.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.prices.dependencies import build_price_service
from di1.modules.prices.public import ReferencePriceRecord
from di1.modules.pricing.dependencies import build_pricing_service
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.decimals import to_plain
from di1.shared.input_kind import InputKind
from tests.fakes.clock import FixedClock
from tests.integration.prices.conftest import DI1F28, MATURED, TODAY

DAY = date(2026, 10, 16)


async def _set(factory: async_sessionmaker[AsyncSession], **price: object) -> ReferencePriceRecord:
    async with SqlAlchemyUnitOfWork(factory) as uow:
        assets = build_asset_reader(uow.session)
        service = build_price_service(
            uow, assets=assets, pricing=build_pricing_service(assets), clock=FixedClock(TODAY)
        )
        return await service.set_reference_price(**price)  # type: ignore[arg-type]


def _request(
    asset_id: UUID = DI1F28,
    *,
    day: date = DAY,
    pu: str | None = None,
    rate: str | None = None,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "reference_date": day,
        "input_kind": InputKind.PU if pu is not None else InputKind.RATE,
        "pu": None if pu is None else Decimal(pu),
        "rate": None if rate is None else Decimal(rate),
    }


async def test_a_typed_rate_stores_the_dc365_pu(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    record = await _set(session_factory, **_request(rate="0.0980"))

    assert (record.input_kind, record.pu, record.rate) == (
        InputKind.RATE,
        Decimal("89250.3147019396"),
        Decimal("0.0980"),
    )
    assert str(record.rate) == "0.0980"  # the typed value keeps its typed scale


async def test_a_typed_pu_stores_the_dc365_rate_at_12_places(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    record = await _set(session_factory, **_request(pu="89250.3147019396"))

    assert (record.input_kind, str(record.pu), str(record.rate)) == (
        InputKind.PU,
        "89250.3147019396",
        "0.098000000000",
    )


async def test_on_the_maturity_date_the_typed_pu_stores_rate_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # MATURED matures on 01/10/2026: on that date d = 0, the PU is typed, the rate is 0 (OQ-1).
    record = await _set(session_factory, **_request(MATURED, day=date(2026, 10, 1), pu="99987.5"))

    assert record.rate is not None
    assert (record.input_kind, to_plain(record.pu), to_plain(record.rate)) == (
        InputKind.PU,
        "99987.5",
        "0.000000000000",
    )
