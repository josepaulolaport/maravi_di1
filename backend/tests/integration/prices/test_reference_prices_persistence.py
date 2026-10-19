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

from di1.modules.prices.application.interfaces.ports import NewReferencePrice
from di1.modules.prices.application.services.price_service import (
    PreferredPriceReader,
    PriceService,
    SetReferencePrice,
)
from di1.modules.prices.infrastructure.persistence.repositories import (
    SqlReferencePriceRepository,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind
from tests.integration.prices.conftest import DI1F28, DI1F29, MATURED
from tests.unit.prices.fakes import CALCULATED_RATE

DAY = date(2026, 10, 16)


def _manual(
    pu: str, *, source: PriceSource = PriceSource.MANUAL, day: date = DAY
) -> SetReferencePrice:
    return SetReferencePrice(
        asset_id=DI1F28,
        reference_date=day,
        input_kind=InputKind.PU,
        pu=Decimal(pu),
        rate=None,
        source=source,
    )


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
    service: PriceService,
    factory: async_sessionmaker[AsyncSession],
    request: SetReferencePrice,
) -> ReferencePriceRecord:
    async with SqlAlchemyUnitOfWork(factory) as uow:
        return await service.set_reference_price(request, uow=uow)


async def _preferred(
    factory: async_sessionmaker[AsyncSession], asset_id: UUID, day: date
) -> ReferencePriceRecord | None:
    async with factory() as session:
        return await PreferredPriceReader(SqlReferencePriceRepository(session)).get_preferred(
            asset_id, day
        )


class TestOnePerSource:
    async def test_a_price_is_stored_exactly_as_typed_and_calculated(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        record = await _set(service, session_factory, _manual("89250.3147019396"))

        assert await _rows(engine) == [
            (DI1F28, DAY, "MANUAL", "PU", Decimal("89250.3147019396"), CALCULATED_RATE)
        ]
        assert record.created_at == record.updated_at
        assert record.created_at.tzinfo is not None

    async def test_adding_again_replaces_the_row_with_a_new_id(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        first = await _set(service, session_factory, _manual("89200.9008841512"))

        second = await _set(service, session_factory, _manual("89250.3147019396"))

        assert second.id != first.id
        assert second.created_at > first.created_at
        assert [row[4] for row in await _rows(engine)] == [Decimal("89250.3147019396")]
        async with session_factory() as session:
            assert await SqlReferencePriceRepository(session).get(first.id) is None

    async def test_concurrent_adds_of_one_key_both_succeed_and_leave_one_row(
        self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
    ) -> None:
        first_written = asyncio.Event()

        async def first() -> ReferencePriceRecord:
            async with SqlAlchemyUnitOfWork(session_factory) as uow:
                record = await SqlReferencePriceRepository.of(uow).replace(
                    _new(Decimal("89200.9008841512"))
                )
                first_written.set()
                await asyncio.sleep(0.3)  # the second write waits on this row's key
                await uow.commit()
                return record

        async def second() -> ReferencePriceRecord:
            await first_written.wait()
            async with SqlAlchemyUnitOfWork(session_factory) as uow:
                record = await SqlReferencePriceRepository.of(uow).replace(
                    _new(Decimal("89250.3147019396"))
                )
                await uow.commit()
                return record

        one, two = await asyncio.gather(first(), second())

        assert one.id != two.id
        assert await _rows(engine) == [
            (DI1F28, DAY, "MANUAL", "PU", Decimal("89250.3147019396"), Decimal("0.1"))
        ]

    async def test_many_concurrent_services_leave_one_row_per_source(
        self,
        service: PriceService,
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
            await connection.execute(insert, {"asset": DI1F28, "day": DAY})
        with pytest.raises(Exception, match="reference_prices_one_per_source"):
            async with engine.begin() as connection:
                await connection.execute(insert, {"asset": DI1F28, "day": DAY})


def _new(pu: Decimal) -> NewReferencePrice:
    return NewReferencePrice(
        asset_id=DI1F28,
        reference_date=DAY,
        source=PriceSource.MANUAL,
        input_kind=InputKind.PU,
        pu=pu,
        rate=Decimal("0.1"),
    )


class TestPreferred:
    async def test_manual_wins_over_b3_and_b3_takes_over_after_its_removal(
        self, service: PriceService, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        b3 = await _set(
            service, session_factory, _manual("89240.4279488087", source=PriceSource.B3)
        )
        manual = await _set(service, session_factory, _manual("89250.3147019396"))
        assert await _preferred(session_factory, DI1F28, DAY) == manual

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service.remove_reference_price(manual.id, uow=uow)

        assert await _preferred(session_factory, DI1F28, DAY) == b3

    async def test_no_carry_forward_to_a_later_date_or_a_weekend(
        self, service: PriceService, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _set(service, session_factory, _manual("89250.3147019396"))

        for later in (date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)):
            assert await _preferred(session_factory, DI1F28, later) is None

    async def test_batch_read_answers_every_pair_in_one_query(
        self,
        service: PriceService,
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
            SetReferencePrice(
                asset_id=DI1F29,
                reference_date=date(2026, 10, 15),
                input_kind=InputKind.RATE,
                pu=None,
                rate=Decimal("0.1045"),
            ),
        )
        statements: list[str] = []

        def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            async with session_factory() as session:
                found = await PreferredPriceReader(
                    SqlReferencePriceRepository(session)
                ).get_preferred_many(
                    [DI1F28, DI1F29], [date(2026, 10, 14), date(2026, 10, 15), DAY]
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        assert found == {
            (DI1F28, DAY): b3,
            (DI1F28, date(2026, 10, 15)): manual_15,
            (DI1F29, date(2026, 10, 15)): other,
        }
        assert len([s for s in statements if "reference_prices" in s]) == 1


class TestLatestPreferred:
    """`get_latest_preferred_many` on PostgreSQL (OQ-48): per asset, the preferred price of the
    latest date that has one, for any number of assets in one statement."""

    async def test_latest_date_then_manual_over_b3_in_one_statement(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        await _set(service, session_factory, _manual("89006.4625467350", day=date(2026, 10, 14)))
        await _set(service, session_factory, _manual("89240.4279488087", source=PriceSource.B3))
        manual_16 = await _set(service, session_factory, _manual("89250.3147019396"))
        older_manual = await _set(
            service,
            session_factory,
            SetReferencePrice(
                asset_id=DI1F29,
                reference_date=date(2026, 10, 9),
                input_kind=InputKind.PU,
                pu=Decimal("80100"),
                rate=None,
            ),
        )
        newer_b3 = await _set(
            service,
            session_factory,
            SetReferencePrice(
                asset_id=DI1F29,
                reference_date=date(2026, 10, 15),
                input_kind=InputKind.PU,
                pu=Decimal("80206.1333187932"),
                rate=None,
                source=PriceSource.B3,
            ),
        )
        statements: list[str] = []

        def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            async with session_factory() as session:
                found = await PreferredPriceReader(
                    SqlReferencePriceRepository(session)
                ).get_latest_preferred_many([DI1F28, DI1F29, MATURED])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        assert older_manual not in found.values()
        assert found == {DI1F28: manual_16, DI1F29: newer_b3}
        assert len([s for s in statements if "reference_prices" in s]) == 1

    async def test_no_asset_asked_runs_no_query(
        self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
    ) -> None:
        statements: list[str] = []

        def count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            async with session_factory() as session:
                found = await PreferredPriceReader(
                    SqlReferencePriceRepository(session)
                ).get_latest_preferred_many([])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        assert (found, statements) == ({}, [])


class TestNoProcessingSideEffects:
    async def test_set_correct_and_remove_touch_no_processing_table(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        # A price write only saves the price: no date is marked and no run is queued (OQ-31).
        await _processed_dates(engine, [date(2026, 10, 15), DAY, date(2026, 10, 17)])
        before = await _processing_tables(engine)

        price = await _set(service, session_factory, _manual("89250.3147019396"))
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service.correct_reference_price(
                price.id, input_kind=InputKind.PU, pu=Decimal("89251"), rate=None, uow=uow
            )
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await service.remove_reference_price(price.id, uow=uow)

        assert await _processing_tables(engine) == before
        assert before[1:] == (0, 0)


class TestCorrection:
    async def test_a_correction_updates_in_place_and_keeps_the_id(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        price = await _set(service, session_factory, _manual("89200.9008841512"))

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            corrected = await service.correct_reference_price(
                price.id, input_kind=InputKind.RATE, pu=None, rate=Decimal("0.0980"), uow=uow
            )

        assert corrected.id == price.id
        assert corrected.created_at == price.created_at
        assert corrected.updated_at > price.updated_at
        assert [row[3:] for row in await _rows(engine)] == [
            ("RATE", Decimal("89006.4625467350"), Decimal("0.0980"))
        ]

    async def test_a_future_date_or_a_matured_contract_writes_nothing(
        self,
        service: PriceService,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        with pytest.raises(DomainError) as future:
            await _set(service, session_factory, _manual("89000", day=date(2026, 10, 20)))
        matured = SetReferencePrice(
            asset_id=MATURED,
            reference_date=DAY,
            input_kind=InputKind.PU,
            pu=Decimal("100000"),
            rate=None,
        )
        with pytest.raises(DomainError) as after_maturity:
            await _set(service, session_factory, matured)

        assert (future.value.code, after_maturity.value.code) == (
            ErrorCode.FUTURE_DATE,
            ErrorCode.CONTRACT_MATURED,
        )
        assert await _rows(engine) == []


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
