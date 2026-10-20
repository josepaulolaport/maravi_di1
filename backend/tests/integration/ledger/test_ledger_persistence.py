"""Ledger against PostgreSQL 16: the one ``ledger.entries`` table, its order, the batch delete
and the atomicity of a write.

Rules: spec §6, §13 item 16 (trades and cash of the same date follow (date, time, seq) across
both types; a mixed multi-delete is all or nothing); §4.2 (an execution price never becomes a
reference price); interfaces "Ledger"; plan §5.C (several trades on one date). User decisions of
2026-10-19: a write touches only the ledger (staleness is removed from the project), and a
deletion removes the entries for good.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from datetime import date, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import build_ledger_reader
from di1.modules.ledger.domain.entries import EntryType
from di1.modules.ledger.domain.listing import ListOrder
from di1.modules.ledger.infrastructure.persistence.repositories import SqlLedgerRepository
from di1.modules.pricing.dependencies import build_pricing_service
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind
from di1.shared.paging import PageParams
from tests.integration.ledger.support import CONTRACTS, TODAY, ServiceOn, fetch
from tests.support.builders import DI1F29, draft_cash, draft_trade
from tests.support.fakes import FakeAssetReader, FakeClock
from tests.support.waits import wait_for_a_lock_waiter

Sessions = async_sessionmaker[AsyncSession]


async def create(service: ServiceOn, sessions: Sessions, draft: object) -> UUID:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        view = await service(uow).create_entry(draft)  # type: ignore[arg-type]
    return view.entry.id


async def delete(service: ServiceOn, sessions: Sessions, *ids: UUID) -> None:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await service(uow).delete_entries(list(ids))


async def test_entries_are_stored_with_their_typed_values_as_typed(
    service: ServiceOn, session_factory: Sessions
) -> None:
    trade_id = await create(service, session_factory, draft_trade())
    cash_id = await create(service, session_factory, draft_cash(amount="-50000.00"))

    rows = await fetch(
        session_factory,
        "SELECT id, type, execution_pu::text, execution_rate::text, input_kind,"
        " cash_amount::text, signed_quantity FROM ledger.entries ORDER BY seq",
    )

    assert [tuple(row) for row in rows] == [
        (trade_id, "TRADE", "89006.4625467350", "0.10", "RATE", None, 10),
        (cash_id, "CASH", None, None, None, "-50000.00", None),
    ]


async def test_the_reader_returns_active_entries_of_each_type_in_order(
    service: ServiceOn, session_factory: Sessions
) -> None:
    day = date(2026, 10, 15)
    late = await create(service, session_factory, draft_trade(day, time(11, 0)))
    early = await create(service, session_factory, draft_trade(day, time(10, 0), quantity=-3))
    same_time = await create(service, session_factory, draft_trade(day, time(11, 0), quantity=2))
    other_day = await create(service, session_factory, draft_trade(date(2026, 10, 14), time(16, 0)))
    gone = await create(service, session_factory, draft_trade(day, time(9, 0)))
    outside = await create(service, session_factory, draft_trade(date(2026, 10, 17)))
    deposit = await create(service, session_factory, draft_cash(day, time(12, 0)))
    withdrawal = await create(service, session_factory, draft_cash(day, time(8, 0), amount="-1.00"))
    await delete(service, session_factory, gone)

    async with session_factory() as session:
        reader = build_ledger_reader(session)
        trades = await reader.get_trades(date(2026, 10, 14), date(2026, 10, 16))
        movements = await reader.get_cash_movements(date(2026, 10, 14), date(2026, 10, 16))

    assert [t.id for t in trades] == [other_day, early, late, same_time]
    assert outside not in {t.id for t in trades}
    assert [m.id for m in movements] == [withdrawal, deposit]
    first = trades[1]
    assert (first.entry_date, first.entry_time, first.signed_quantity) == (day, time(10), -3)
    assert first.input_kind is InputKind.RATE
    assert movements[0].cash_amount == Decimal("-1.00")
    assert movements[0].entry_time == time(8, 0)


async def test_has_entries_on_or_before_checks_dates_and_type(
    service: ServiceOn, session_factory: Sessions
) -> None:
    # Processing's zero-state check (OQ-31, OQ-37): positions ask for trades, cash for any type.
    async def has(day: date, entry_type: EntryType | None = None) -> bool:
        async with session_factory() as session:
            return await build_ledger_reader(session).has_entries_on_or_before(
                day, entry_type=entry_type
            )

    assert not await has(TODAY)
    await create(service, session_factory, draft_cash(date(2026, 10, 14)))
    await create(service, session_factory, draft_trade(date(2026, 10, 16)))
    deleted = await create(service, session_factory, draft_trade(date(2026, 10, 13)))
    await delete(service, session_factory, deleted)

    assert not await has(date(2026, 10, 13))  # a deleted entry no longer exists (OQ-32)
    assert await has(date(2026, 10, 14))  # on the day itself
    assert await has(date(2026, 10, 14), EntryType.CASH)
    assert not await has(date(2026, 10, 15), EntryType.TRADE)
    assert await has(date(2026, 10, 16), EntryType.TRADE)
    assert await has(TODAY)


async def test_trades_and_cash_of_one_date_follow_time_then_seq(
    service: ServiceOn, session_factory: Sessions
) -> None:
    day = date(2026, 10, 16)
    sell = await create(service, session_factory, draft_trade(day, time(15, 0), quantity=-4))
    withdrawal = await create(
        service, session_factory, draft_cash(day, time(17, 30), amount="-50.00")
    )
    deposit = await create(
        service, session_factory, draft_cash(day, time(15, 0))
    )  # same time, later seq
    buy = await create(service, session_factory, draft_trade(day, time(9, 0)))

    async with session_factory() as session:
        uow = _ReadOnly(session)
        page = await service(uow).list_entries(
            start_date=day,
            end_date=day,
            search=None,
            order=ListOrder.ASC,
            page=PageParams(),
        )

    assert [item.entry.id for item in page.items] == [buy, sell, deposit, withdrawal]


async def test_keyset_pages_cover_every_entry_once_in_both_orders(
    service: ServiceOn, session_factory: Sessions
) -> None:
    ids = [
        await create(service, session_factory, draft_trade(entry_time=time(10, 0)))
        for _ in range(3)
    ]
    ids += [await create(service, session_factory, draft_cash(date(2026, 10, 15), time(10, 0)))]
    ids += [await create(service, session_factory, draft_cash(date(2026, 10, 13), time(23, 59)))]
    expected_asc = [ids[4], *ids[:3], ids[3]]

    for order, expected in ((ListOrder.ASC, expected_asc), (ListOrder.DESC, expected_asc[::-1])):
        seen: list[UUID] = []
        cursor: str | None = None
        while True:
            async with session_factory() as session:
                page = await service(_ReadOnly(session)).list_entries(
                    start_date=date(2026, 10, 1),
                    end_date=TODAY,
                    search=None,
                    order=order,
                    page=PageParams(limit=2, cursor=cursor),
                )
            seen += [item.entry.id for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
        assert seen == expected


async def test_a_cash_description_is_stored_trimmed_and_read_back(
    service: ServiceOn, session_factory: Sessions
) -> None:
    described = await create(service, session_factory, draft_cash(description="  Aporte inicial "))
    blank = await create(
        service, session_factory, draft_cash(entry_time=time(10, 0), description="  ")
    )

    rows = await fetch(session_factory, "SELECT id, description FROM ledger.entries ORDER BY seq")
    async with session_factory() as session:
        movements = await build_ledger_reader(session).get_cash_movements(date(2026, 10, 14), TODAY)

    assert [tuple(row) for row in rows] == [(described, "Aporte inicial"), (blank, None)]
    assert [m.description for m in movements] == ["Aporte inicial", None]


async def test_the_search_matches_a_description_ignoring_case_and_accents(
    service: ServiceOn, session_factory: Sessions
) -> None:
    opening = await create(service, session_factory, draft_cash(description="Aplicação inicial"))
    redemption = await create(
        service, session_factory, draft_cash(amount="-10.00", description="Resgate 10% _cotista_")
    )
    shouting = await create(
        service, session_factory, draft_cash(entry_time=time(9, 30), description="APLICAÇÃO EXTRA")
    )
    await create(service, session_factory, draft_cash(entry_time=time(10, 0)))
    await create(service, session_factory, draft_trade())

    async def search(text: str) -> set[UUID]:
        async with session_factory() as session:
            page = await service(_ReadOnly(session)).list_entries(
                start_date=date(2026, 10, 1),
                end_date=TODAY,
                search=text,
                order=ListOrder.DESC,
                page=PageParams(),
            )
        return {item.entry.id for item in page.items}

    assert await search("APLICACAO") == {opening, shouting}
    assert await search("aplicação ini") == {opening}
    assert await search("acao extra") == {shouting}
    assert await search("a\x00") == set()  # never sent to PostgreSQL, which refuses NUL
    assert await search("10%") == {redemption}
    assert await search("_cotista_") == {redemption}
    assert await search("%") == {redemption}  # a literal percent sign, not a wildcard
    assert await search("e_1") == set()  # "_" is literal too: no "e?1" wildcard match


async def test_the_search_filters_in_the_database(
    service: ServiceOn, session_factory: Sessions
) -> None:
    f28 = await create(service, session_factory, draft_trade())
    f29 = await create(
        service,
        session_factory,
        draft_trade(date(2026, 10, 15), rate="0.093203413834", contract_id=DI1F29.id),
    )
    deposit = await create(service, session_factory, draft_cash())
    withdrawal = await create(service, session_factory, draft_cash(amount="-10.00"))

    async def search(text: str) -> set[UUID]:
        async with session_factory() as session:
            page = await service(_ReadOnly(session)).list_entries(
                start_date=date(2026, 10, 1),
                end_date=TODAY,
                search=text,
                order=ListOrder.DESC,
                page=PageParams(),
            )
        return {item.entry.id for item in page.items}

    assert await search("di1f2") == {f28, f29}
    assert await search("F29") == {f29}
    assert await search("Aporte") == {deposit}
    assert await search("retirada") == {withdrawal}
    assert await search("ra") == {withdrawal}  # in "retirada", not in "aporte"
    assert await search("nada") == set()


async def test_a_mixed_batch_is_all_or_nothing(
    service: ServiceOn, session_factory: Sessions
) -> None:
    deposit = await create(service, session_factory, draft_cash(date(2026, 10, 14)))
    sell = await create(service, session_factory, draft_trade(date(2026, 10, 16), quantity=-4))
    buy = await create(service, session_factory, draft_trade(date(2026, 10, 17)))

    with pytest.raises(DomainError) as error:
        await delete(service, session_factory, deposit, sell, uuid4())
    assert error.value.code is ErrorCode.NOT_FOUND
    assert len(await fetch(session_factory, "SELECT id FROM ledger.entries")) == 3

    await delete(service, session_factory, deposit, sell)

    rows = await fetch(session_factory, "SELECT id FROM ledger.entries")
    assert [row.id for row in rows] == [buy]


async def test_a_deleted_entry_is_gone_for_good(
    service: ServiceOn, session_factory: Sessions
) -> None:
    entry = await create(service, session_factory, draft_cash())
    await delete(service, session_factory, entry)

    with pytest.raises(DomainError) as error:
        await delete(service, session_factory, entry)

    assert error.value.code is ErrorCode.NOT_FOUND
    assert await fetch(session_factory, "SELECT id FROM ledger.entries") == []


async def test_an_overlapping_deletion_waits_then_deletes_nothing(
    service: ServiceOn, session_factory: Sessions, engine: AsyncEngine
) -> None:
    a, b, c = [
        await create(service, session_factory, draft_cash(amount=f"{n}.00")) for n in (1, 2, 3)
    ]
    first_holds_its_locks, release_first = asyncio.Event(), asyncio.Event()

    class HoldingRepository(SqlLedgerRepository):
        async def delete(self, ids: Collection[UUID]) -> None:
            await super().delete(ids)
            first_holds_its_locks.set()
            await release_first.wait()

    assets = FakeAssetReader(*CONTRACTS)

    def holding(uow: UnitOfWork) -> LedgerService:
        return LedgerService(
            HoldingRepository(uow.session),
            uow,
            clock=FakeClock(TODAY),
            assets=assets,
            pricing=build_pricing_service(assets),
        )

    first = asyncio.create_task(delete(holding, session_factory, a, b))
    await asyncio.wait_for(first_holds_its_locks.wait(), timeout=5)
    second = asyncio.create_task(delete(service, session_factory, b, c))
    await wait_for_a_lock_waiter(engine)  # the second batch waits on b, locked by the first
    assert not second.done()

    release_first.set()
    await asyncio.wait_for(first, timeout=10)
    with pytest.raises(DomainError) as error:
        await asyncio.wait_for(second, timeout=10)

    assert error.value.code is ErrorCode.NOT_FOUND  # b is gone: all or nothing, c stays
    rows = await fetch(session_factory, "SELECT id FROM ledger.entries")
    assert [row.id for row in rows] == [c]


async def test_a_write_only_saves_the_fact(service: ServiceOn, session_factory: Sessions) -> None:
    # Spec §13 items 9 and 16, OQ-31: creating or deleting entries leaves processed dates as
    # they are (no staleness) and never enqueues a run.
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO processing.date_status"
                " (date, portfolio, cash, portfolio_processed_at, cash_processed_at, updated_at)"
                " VALUES (:day, 'PROCESSED', 'PROCESSED_WITH_ISSUES',"
                " '2026-10-17 18:00-03', '2026-10-17 18:01-03', '2026-10-17 18:02-03')"
            ),
            {"day": date(2026, 10, 16)},
        )
    statuses = "SELECT * FROM processing.date_status ORDER BY date"
    before = await fetch(session_factory, statuses)
    assert len(before) == 1 and before[0].cash_processed_at is not None

    deposit = await create(service, session_factory, draft_cash(date(2026, 10, 14)))
    sell = await create(service, session_factory, draft_trade(date(2026, 10, 16), quantity=-4))
    await delete(service, session_factory, deposit, sell)

    assert await fetch(session_factory, statuses) == before
    assert await fetch(session_factory, "SELECT id FROM processing.requests") == []


async def test_an_execution_price_never_becomes_a_reference_price(
    service: ServiceOn, session_factory: Sessions
) -> None:
    await create(service, session_factory, draft_trade())
    await create(
        service,
        session_factory,
        draft_trade(date(2026, 10, 15), rate="0.093203413834", contract_id=DI1F29.id),
    )

    assert await fetch(session_factory, "SELECT id FROM prices.reference_prices") == []


async def test_a_rejected_entry_writes_nothing(
    service: ServiceOn, session_factory: Sessions
) -> None:
    with pytest.raises(DomainError):
        await create(service, session_factory, draft_trade(date(2026, 10, 19)))

    assert await fetch(session_factory, "SELECT id FROM ledger.entries") == []


class _ReadOnly:
    """A Unit of Work over a plain session for the list read, which never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def commit(self) -> None:
        raise AssertionError("a read never commits")
