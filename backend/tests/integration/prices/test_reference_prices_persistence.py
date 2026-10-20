"""Prices against PostgreSQL, with the real Asset reader and Pricing service: the stored DC/365
pair, one row per (asset, date, source) under concurrency, MANUAL over B3, B3 after a MANUAL
removal, exact dates only and the latest date (spec §4.1, §5, §13 items 7 and 17; plan §5.D;
OQ-3, OQ-25, OQ-26 item 7, OQ-48).

DI1F28 matures on 03/01/2028: on 16/10/2026 (444 calendar days) the PU 89250.3147019396 is the
rate 0.098000000000 (the frontend demo fixtures, ``frontend/src/api/mocks/fixtures.ts``,
recomputed with ``decimal`` at 34 digits, half-up).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.prices.application.services.price_service import DefaultPriceReader
from di1.modules.prices.infrastructure.persistence.repositories import (
    SqlReferencePriceRepository,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.input_kind import InputKind
from tests.integration.prices.support import ServiceOn
from tests.support.builders import DI1F28, DI1F29, DI1V26
from tests.support.waits import wait_for_a_lock_waiter

DAY = date(2026, 10, 16)
_COUNT_ID = text("SELECT count(*) FROM prices.reference_prices WHERE id = :id")


def _manual(
    pu: str | None,
    *,
    source: PriceSource = PriceSource.MANUAL,
    day: date = DAY,
    asset_id: UUID = DI1F28.id,
    rate: str | None = None,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "reference_date": day,
        "input_kind": InputKind.PU if pu is not None else InputKind.RATE,
        "pu": None if pu is None else Decimal(pu),
        "rate": None if rate is None else Decimal(rate),
        "source": source,
    }


async def _rows(engine: AsyncEngine) -> list[tuple[object, ...]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT asset_id, reference_date, source, input_kind, pu::text, rate::text"
                " FROM prices.reference_prices ORDER BY reference_date, source"
            )
        )
        return [tuple(row) for row in result]


async def _set(
    service: ServiceOn,
    factory: async_sessionmaker[AsyncSession],
    request: dict[str, object],
) -> ReferencePriceRecord:
    async with SqlAlchemyUnitOfWork(factory) as uow:
        return await service(uow).set_reference_price(**request)  # type: ignore[arg-type]


async def _remove(
    service: ServiceOn, factory: async_sessionmaker[AsyncSession], price_id: UUID
) -> None:
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await service(uow).remove_reference_price(price_id)


async def _preferred(
    factory: async_sessionmaker[AsyncSession], asset_id: UUID, day: date
) -> ReferencePriceRecord | None:
    async with factory() as session:
        found = await DefaultPriceReader(SqlReferencePriceRepository(session)).get(
            [asset_id], [day]
        )
        return found.get((asset_id, day))


async def _latest(
    factory: async_sessionmaker[AsyncSession], asset_id: UUID
) -> ReferencePriceRecord | None:
    async with factory() as session:
        found = await DefaultPriceReader(SqlReferencePriceRepository(session)).latest([asset_id])
    return found.get(asset_id)


# --- one row per (asset, date, source) ---------------------------------------------------------


async def test_a_typed_pu_is_stored_as_typed_with_the_dc365_rate_at_12_places(
    service: ServiceOn,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    record = await _set(service, session_factory, _manual("89250.3147019396"))

    assert await _rows(engine) == [
        (DI1F28.id, DAY, "MANUAL", "PU", "89250.3147019396", "0.098000000000")
    ]
    assert record.created_at == record.updated_at
    assert record.created_at.tzinfo is not None


async def test_adding_again_replaces_the_row_of_its_source_with_a_new_id(
    service: ServiceOn,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
    first = await _set(service, session_factory, _manual("89200.9008841512"))

    second = await _set(service, session_factory, _manual("89250.3147019396"))

    assert second.id != first.id
    assert second.created_at > first.created_at
    assert [(row[2], row[4]) for row in await _rows(engine)] == [
        ("B3", "89240.4279488087"),
        ("MANUAL", "89250.3147019396"),
    ]
    async with session_factory() as session:
        assert await session.scalar(_COUNT_ID, {"id": first.id}) == 0


async def test_concurrent_adds_of_one_key_both_succeed_and_leave_one_row(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    first_written = asyncio.Event()

    async def first() -> ReferencePriceRecord:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            record = await SqlReferencePriceRepository(uow.session).replace(
                asset_id=DI1F28.id,
                reference_date=DAY,
                source=PriceSource.MANUAL,
                input_kind=InputKind.PU,
                pu=Decimal("89200.9008841512"),
                rate=Decimal("0.1"),
            )
            first_written.set()
            await wait_for_a_lock_waiter(engine)  # the second write waits on this row's key
            await uow.commit()
            return record

    async def second() -> ReferencePriceRecord:
        await first_written.wait()
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            record = await SqlReferencePriceRepository(uow.session).replace(
                asset_id=DI1F28.id,
                reference_date=DAY,
                source=PriceSource.MANUAL,
                input_kind=InputKind.PU,
                pu=Decimal("89250.3147019396"),
                rate=Decimal("0.1"),
            )
            await uow.commit()
            return record

    one, two = await asyncio.gather(first(), second())

    assert one.id != two.id
    assert await _rows(engine) == [(DI1F28.id, DAY, "MANUAL", "PU", "89250.3147019396", "0.1")]


async def test_many_concurrent_services_leave_one_row_per_source(
    service: ServiceOn,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    pus = [f"8920{i}.0000000000" for i in range(6)]

    await asyncio.gather(
        *(_set(service, session_factory, _manual(pu)) for pu in pus),
        _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)),
    )

    rows = await _rows(engine)
    assert [(row[2], row[4] in pus) for row in rows] == [("B3", False), ("MANUAL", True)]


async def test_the_schema_refuses_a_second_row_of_one_key(engine: AsyncEngine) -> None:
    insert = text(
        "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu)"
        " VALUES (:asset, :day, 'MANUAL', 'PU', 89000)"
    )
    async with engine.begin() as connection:
        await connection.execute(insert, {"asset": DI1F28.id, "day": DAY})
    with pytest.raises(Exception, match="reference_prices_one_per_source"):
        async with engine.begin() as connection:
            await connection.execute(insert, {"asset": DI1F28.id, "day": DAY})


# --- PriceReader.get: the preferred price of exact dates ---------------------------------------


async def test_manual_wins_over_b3_and_b3_takes_over_after_its_removal(
    service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    b3 = await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
    manual = await _set(service, session_factory, _manual("89250.3147019396"))
    assert await _preferred(session_factory, DI1F28.id, DAY) == manual

    await _remove(service, session_factory, manual.id)

    assert await _preferred(session_factory, DI1F28.id, DAY) == b3


async def test_no_carry_forward_to_a_later_date_or_a_weekend(
    service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _set(service, session_factory, _manual("89250.3147019396"))

    for later in (date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)):
        assert await _preferred(session_factory, DI1F28.id, later) is None


async def test_batch_read_answers_every_pair_in_one_query(
    service: ServiceOn,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    b3 = await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
    manual_15 = await _set(
        service, session_factory, _manual("89128.4824345118", day=date(2026, 10, 15))
    )
    other = await _set(
        service,
        session_factory,
        _manual(None, asset_id=DI1F29.id, day=date(2026, 10, 15), rate="0.1045"),
    )
    statements: list[str] = []

    def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with session_factory() as session:
            found = await DefaultPriceReader(SqlReferencePriceRepository(session)).get(
                [DI1F28.id, DI1F29.id], [date(2026, 10, 14), date(2026, 10, 15), DAY]
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert found == {
        (DI1F28.id, DAY): b3,
        (DI1F28.id, date(2026, 10, 15)): manual_15,
        (DI1F29.id, date(2026, 10, 15)): other,
    }
    assert len([s for s in statements if "reference_prices" in s]) == 1


# --- PriceReader.latest (OQ-48) ----------------------------------------------------------------


async def test_latest_date_then_manual_over_b3_in_one_statement(
    service: ServiceOn,
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
) -> None:
    await _set(service, session_factory, _manual("89006.4625467350", day=date(2026, 10, 14)))
    await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
    manual_16 = await _set(service, session_factory, _manual("89250.3147019396"))
    await _set(  # an older MANUAL of DI1F29, not its latest
        service,
        session_factory,
        _manual("80100", asset_id=DI1F29.id, day=date(2026, 10, 9)),
    )
    newer_b3 = await _set(
        service,
        session_factory,
        _manual(
            "80206.1333187932",
            asset_id=DI1F29.id,
            day=date(2026, 10, 15),
            source=PriceSource.B3,
        ),
    )
    statements: list[str] = []

    def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with session_factory() as session:
            found = await DefaultPriceReader(SqlReferencePriceRepository(session)).latest(
                [DI1F28.id, DI1F29.id, DI1V26.id]
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert found == {DI1F28.id: manual_16, DI1F29.id: newer_b3}
    assert len(statements) == 1


async def test_removing_the_latest_price_falls_back_to_the_previous_date(
    service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    manual_14 = await _set(
        service, session_factory, _manual("89006.4625467350", day=date(2026, 10, 14))
    )
    b3_16 = await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))

    await _remove(service, session_factory, b3_16.id)

    assert await _latest(session_factory, DI1F28.id) == manual_14


async def test_removing_manual_on_the_latest_date_lets_b3_of_that_date_prevail(
    service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    b3_16 = await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
    manual_16 = await _set(service, session_factory, _manual("89250.3147019396"))
    assert await _latest(session_factory, DI1F28.id) == manual_16

    await _remove(service, session_factory, manual_16.id)

    assert await _latest(session_factory, DI1F28.id) == b3_16
