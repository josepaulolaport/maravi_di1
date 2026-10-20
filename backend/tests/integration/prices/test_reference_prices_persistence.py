"""Prices against PostgreSQL: one row per (asset, date, source) under concurrency, MANUAL over
B3, B3 after a MANUAL removal, exact dates only, and price writes that touch no processing table
(spec §5, §13 item 17; plan §5.D; OQ-25, OQ-26 item 7, OQ-31)."""

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
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind
from tests.integration.prices.support import ServiceOn
from tests.support.builders import DI1F28, DI1F29, DI1V26
from tests.unit.prices.fakes import CALCULATED_RATE

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
                "SELECT asset_id, reference_date, source, input_kind, pu, rate"
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


async def _preferred(
    factory: async_sessionmaker[AsyncSession], asset_id: UUID, day: date
) -> ReferencePriceRecord | None:
    async with factory() as session:
        found = await DefaultPriceReader(SqlReferencePriceRepository(session)).get(
            [asset_id], [day]
        )
        return found.get((asset_id, day))


class TestOnePerSource:
    async def test_a_price_is_stored_exactly_as_typed_and_calculated(
        self,
        service: ServiceOn,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        record = await _set(service, session_factory, _manual("89250.3147019396"))

        assert await _rows(engine) == [
            (DI1F28.id, DAY, "MANUAL", "PU", Decimal("89250.3147019396"), CALCULATED_RATE)
        ]
        assert record.created_at == record.updated_at
        assert record.created_at.tzinfo is not None

    async def test_adding_again_replaces_the_row_with_a_new_id(
        self,
        service: ServiceOn,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        first = await _set(service, session_factory, _manual("89200.9008841512"))

        second = await _set(service, session_factory, _manual("89250.3147019396"))

        assert second.id != first.id
        assert second.created_at > first.created_at
        assert [row[4] for row in await _rows(engine)] == [Decimal("89250.3147019396")]
        async with session_factory() as session:
            assert await session.scalar(_COUNT_ID, {"id": first.id}) == 0

    async def test_concurrent_adds_of_one_key_both_succeed_and_leave_one_row(
        self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
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
                await asyncio.sleep(0.3)  # the second write waits on this row's key
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
        assert await _rows(engine) == [
            (DI1F28.id, DAY, "MANUAL", "PU", Decimal("89250.3147019396"), Decimal("0.1"))
        ]

    async def test_many_concurrent_services_leave_one_row_per_source(
        self,
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
        assert [(row[2], row[4] in {Decimal(p) for p in pus}) for row in rows] == [
            ("B3", False),
            ("MANUAL", True),
        ]

    async def test_the_schema_refuses_a_second_row_of_one_key(self, engine: AsyncEngine) -> None:
        insert = text(
            "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu)"
            " VALUES (:asset, :day, 'MANUAL', 'PU', 89000)"
        )
        async with engine.begin() as connection:
            await connection.execute(insert, {"asset": DI1F28.id, "day": DAY})
        with pytest.raises(Exception, match="reference_prices_one_per_source"):
            async with engine.begin() as connection:
                await connection.execute(insert, {"asset": DI1F28.id, "day": DAY})


class TestPreferred:
    async def test_manual_wins_over_b3_and_b3_takes_over_after_its_removal(
        self, service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        b3 = await _set(
            service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)
        )
        manual = await _set(service, session_factory, _manual("89250.3147019396"))
        assert await _preferred(session_factory, DI1F28.id, DAY) == manual

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service(uow).remove_reference_price(manual.id)

        assert await _preferred(session_factory, DI1F28.id, DAY) == b3

    async def test_no_carry_forward_to_a_later_date_or_a_weekend(
        self, service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _set(service, session_factory, _manual("89250.3147019396"))

        for later in (date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)):
            assert await _preferred(session_factory, DI1F28.id, later) is None

    async def test_batch_read_answers_every_pair_in_one_query(
        self,
        service: ServiceOn,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        b3 = await _set(
            service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)
        )
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


class TestLatest:
    """`PriceReader.latest` on PostgreSQL (OQ-48): per asset, the winning price of the
    latest date that has one, for any number of assets in one statement."""

    async def test_latest_date_then_manual_over_b3_in_one_statement(
        self,
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
        self, service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        manual_14 = await _set(
            service, session_factory, _manual("89006.4625467350", day=date(2026, 10, 14))
        )
        b3_16 = await _set(
            service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service(uow).remove_reference_price(b3_16.id)

        assert await _latest(session_factory, DI1F28.id) == manual_14

    async def test_removing_manual_on_the_latest_date_lets_b3_of_that_date_prevail(
        self, service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        b3_16 = await _set(
            service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)
        )
        manual_16 = await _set(service, session_factory, _manual("89250.3147019396"))
        assert await _latest(session_factory, DI1F28.id) == manual_16

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service(uow).remove_reference_price(manual_16.id)

        assert await _latest(session_factory, DI1F28.id) == b3_16

    async def test_no_asset_asked_runs_no_query(
        self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
    ) -> None:
        statements: list[str] = []

        def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            async with session_factory() as session:
                found = await DefaultPriceReader(SqlReferencePriceRepository(session)).latest([])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        assert (found, statements) == ({}, [])


class TestNoProcessingSideEffects:
    async def test_set_correct_and_remove_touch_no_processing_table(
        self,
        service: ServiceOn,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        # A price write only saves the price: no date is marked and no run is queued (OQ-31).
        await _processed_dates(engine, [date(2026, 10, 15), DAY, date(2026, 10, 17)])
        before = await _processing_tables(engine)

        await _set(service, session_factory, _manual("89250.3147019396"))
        replaced = await _set(service, session_factory, _manual("89251"))
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service(uow).remove_reference_price(replaced.id)

        assert await _processing_tables(engine) == before
        assert before[1:] == (0, 0)


class TestRefusedWrites:
    async def test_a_future_date_or_a_matured_contract_writes_nothing(
        self,
        service: ServiceOn,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        with pytest.raises(DomainError) as future:
            await _set(service, session_factory, _manual("89000", day=date(2026, 10, 20)))
        matured = _manual("100000", asset_id=DI1V26.id)
        with pytest.raises(DomainError) as after_maturity:
            await _set(service, session_factory, matured)

        assert (future.value.code, after_maturity.value.code) == (
            ErrorCode.FUTURE_DATE,
            ErrorCode.CONTRACT_MATURED,
        )
        assert await _rows(engine) == []


async def _latest(
    factory: async_sessionmaker[AsyncSession], asset_id: UUID
) -> ReferencePriceRecord | None:
    async with factory() as session:
        found = await DefaultPriceReader(SqlReferencePriceRepository(session)).latest([asset_id])
    return found.get(asset_id)


async def _processed_dates(engine: AsyncEngine, dates: list[date]) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO processing.date_status (date, portfolio, portfolio_processed_at)"
                " VALUES (:day, 'PROCESSED', now())"
            ),
            [{"day": day} for day in dates],
        )


async def _processing_tables(
    engine: AsyncEngine,
) -> tuple[list[tuple[object, ...]], int, int]:
    """Every ``date_status`` row, and the numbers of processing requests and outbox messages."""
    async with engine.connect() as connection:
        statuses = await connection.execute(
            text("SELECT * FROM processing.date_status ORDER BY date")
        )
        requests = await connection.scalar(text("SELECT count(*) FROM processing.requests"))
        outbox = await connection.scalar(text("SELECT count(*) FROM platform.outbox_messages"))
        return [tuple(row) for row in statuses], int(requests or 0), int(outbox or 0)
