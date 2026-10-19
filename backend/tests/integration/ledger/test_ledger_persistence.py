"""Ledger against PostgreSQL 16: the one ``ledger.entries`` table, its order, the batch soft
delete and the atomicity of a write with its invalidation.

Rules: spec §6, §13 item 16 (trades and cash of the same date follow (date, time, seq) across
both types; a mixed multi-delete is all or nothing, shares the batch id and marks each chain once
from its earliest date); §4.2 (an execution price never becomes a reference price); interfaces
"Ledger" and "Transaction boundaries" 1 (fact and invalidation in one transaction); plan §5.C
(rollback when invalidation fails, several trades on one date, soft-delete idempotence).
"""

from __future__ import annotations

import asyncio
from datetime import date, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.dependencies import create_ledger_service, ledger_reader
from di1.modules.ledger.domain.listing import ListOrder
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from di1.shared.clock import FixedClock
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.input_kind import InputKind
from tests.fakes.processing import CashMovementsChanged, RecordingInvalidator, TradesChanged
from tests.integration.ledger.support import TODAY, cash, fetch, trade
from tests.unit.ledger.fakes import DI1F29, CalculatorPricer, FakeAssets

Sessions = async_sessionmaker[AsyncSession]


async def create(service: LedgerService, sessions: Sessions, draft: object) -> UUID:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        view = await service.create_entry(draft, uow=uow)  # type: ignore[arg-type]
    return view.entry.id


async def delete(service: LedgerService, sessions: Sessions, *ids: UUID) -> None:
    async with SqlAlchemyUnitOfWork(sessions) as uow:
        await service.delete_entries(list(ids), uow=uow)


async def test_entries_are_stored_with_their_typed_values_as_typed(
    service: LedgerService, session_factory: Sessions
) -> None:
    trade_id = await create(service, session_factory, trade())
    cash_id = await create(service, session_factory, cash(amount="-50000.00"))

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
    service: LedgerService, session_factory: Sessions
) -> None:
    day = date(2026, 10, 15)
    late = await create(service, session_factory, trade(day, time(11, 0)))
    early = await create(service, session_factory, trade(day, time(10, 0), quantity=-3))
    same_time = await create(service, session_factory, trade(day, time(11, 0), quantity=2))
    other_day = await create(service, session_factory, trade(date(2026, 10, 14), time(16, 0)))
    gone = await create(service, session_factory, trade(day, time(9, 0)))
    outside = await create(service, session_factory, trade(date(2026, 10, 17)))
    deposit = await create(service, session_factory, cash(day, time(12, 0)))
    withdrawal = await create(service, session_factory, cash(day, time(8, 0), amount="-1.00"))
    await delete(service, session_factory, gone)

    async with session_factory() as session:
        reader = ledger_reader(session)
        trades = await reader.get_trades(date(2026, 10, 14), date(2026, 10, 16))
        movements = await reader.get_cash_movements(date(2026, 10, 14), date(2026, 10, 16))

    assert [t.id for t in trades] == [other_day, early, late, same_time]
    assert outside not in {t.id for t in trades}
    assert [m.id for m in movements] == [withdrawal, deposit]
    first = trades[1]
    assert (first.trade_date, first.trade_time, first.signed_quantity) == (day, time(10), -3)
    assert first.input_kind is InputKind.RATE
    assert movements[0].amount == Decimal("-1.00")
    assert movements[0].movement_time == time(8, 0)


async def test_trades_and_cash_of_one_date_follow_time_then_seq(
    service: LedgerService, session_factory: Sessions
) -> None:
    day = date(2026, 10, 16)
    sell = await create(service, session_factory, trade(day, time(15, 0), quantity=-4))
    withdrawal = await create(service, session_factory, cash(day, time(17, 30), amount="-50.00"))
    deposit = await create(service, session_factory, cash(day, time(15, 0)))  # same time, later seq
    buy = await create(service, session_factory, trade(day, time(9, 0)))

    async with session_factory() as session:
        uow = _ReadOnly(session)
        page = await service.list_entries(
            start_date=day,
            end_date=day,
            search=None,
            order=ListOrder.ASC,
            limit=None,
            cursor=None,
            uow=uow,
        )

    assert [item.entry.id for item in page.items] == [buy, sell, deposit, withdrawal]


async def test_keyset_pages_cover_every_entry_once_in_both_orders(
    service: LedgerService, session_factory: Sessions
) -> None:
    ids = [await create(service, session_factory, trade(entry_time=time(10, 0))) for _ in range(3)]
    ids += [await create(service, session_factory, cash(date(2026, 10, 15), time(10, 0)))]
    ids += [await create(service, session_factory, cash(date(2026, 10, 13), time(23, 59)))]
    expected_asc = [ids[4], *ids[:3], ids[3]]

    for order, expected in ((ListOrder.ASC, expected_asc), (ListOrder.DESC, expected_asc[::-1])):
        seen: list[UUID] = []
        cursor: str | None = None
        while True:
            async with session_factory() as session:
                page = await service.list_entries(
                    start_date=date(2026, 10, 1),
                    end_date=TODAY,
                    search=None,
                    order=order,
                    limit=2,
                    cursor=cursor,
                    uow=_ReadOnly(session),
                )
            seen += [item.entry.id for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
        assert seen == expected


async def test_the_search_filters_in_the_database(
    service: LedgerService, session_factory: Sessions
) -> None:
    f28 = await create(service, session_factory, trade())
    f29 = await create(
        service,
        session_factory,
        trade(date(2026, 10, 15), rate="0.093203413834", contract_id=DI1F29.id),
    )
    deposit = await create(service, session_factory, cash())
    withdrawal = await create(service, session_factory, cash(amount="-10.00"))

    async def search(text: str) -> set[UUID]:
        async with session_factory() as session:
            page = await service.list_entries(
                start_date=date(2026, 10, 1),
                end_date=TODAY,
                search=text,
                order=ListOrder.DESC,
                limit=None,
                cursor=None,
                uow=_ReadOnly(session),
            )
        return {item.entry.id for item in page.items}

    assert await search("di1f2") == {f28, f29}
    assert await search("F29") == {f29}
    assert await search("Aporte") == {deposit}
    assert await search("retirada") == {withdrawal}
    assert await search("ra") == {withdrawal}  # in "retirada", not in "aporte"
    assert await search("nada") == set()


async def test_a_failing_invalidation_rolls_back_the_write(session_factory: Sessions) -> None:
    class FailingInvalidator(RecordingInvalidator):
        async def trades_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
            raise RuntimeError("date_status is unavailable")

        async def cash_movements_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
            raise RuntimeError("date_status is unavailable")

    assets = FakeAssets()
    failing = create_ledger_service(
        clock=FixedClock(TODAY),
        assets=assets,
        pricer=CalculatorPricer(assets),
        invalidator=FailingInvalidator(),
    )

    for draft in (trade(), cash()):
        with pytest.raises(RuntimeError):
            await create(failing, session_factory, draft)

    assert await fetch(session_factory, "SELECT id FROM ledger.entries") == []


async def test_a_failing_invalidation_rolls_back_a_deletion(
    service: LedgerService, session_factory: Sessions
) -> None:
    entry = await create(service, session_factory, trade())

    class FailingInvalidator(RecordingInvalidator):
        async def trades_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
            raise RuntimeError("date_status is unavailable")

    assets = FakeAssets()
    failing = create_ledger_service(
        clock=FixedClock(TODAY),
        assets=assets,
        pricer=CalculatorPricer(assets),
        invalidator=FailingInvalidator(),
    )
    with pytest.raises(RuntimeError):
        await delete(failing, session_factory, entry)

    rows = await fetch(session_factory, "SELECT deleted_at, deletion_batch_id FROM ledger.entries")
    assert [tuple(row) for row in rows] == [(None, None)]


async def test_a_mixed_batch_is_all_or_nothing_with_one_batch_id(
    service: LedgerService, session_factory: Sessions, invalidator: RecordingInvalidator
) -> None:
    deposit = await create(service, session_factory, cash(date(2026, 10, 14)))
    sell = await create(service, session_factory, trade(date(2026, 10, 16), quantity=-4))
    buy = await create(service, session_factory, trade(date(2026, 10, 17)))
    invalidator.calls.clear()

    with pytest.raises(DomainError) as error:
        await delete(service, session_factory, deposit, sell, uuid4())
    assert error.value.code is ErrorCode.NOT_FOUND
    assert (
        await fetch(session_factory, "SELECT id FROM ledger.entries WHERE deleted_at IS NOT NULL")
        == []
    )
    assert invalidator.calls == []

    await delete(service, session_factory, buy, deposit, sell)

    rows = await fetch(
        session_factory,
        "SELECT id, deletion_batch_id FROM ledger.entries WHERE deleted_at IS NOT NULL",
    )
    assert {row.id for row in rows} == {deposit, sell, buy}
    assert len({row.deletion_batch_id for row in rows}) == 1
    assert None not in {row.deletion_batch_id for row in rows}
    assert all(isinstance(c, TradesChanged | CashMovementsChanged) for c in invalidator.calls)
    assert [(type(c), c.effective_date) for c in invalidator.calls] == [  # type: ignore[union-attr]
        (CashMovementsChanged, date(2026, 10, 14)),
        (TradesChanged, date(2026, 10, 16)),
    ]


async def test_soft_delete_is_idempotent(
    service: LedgerService, session_factory: Sessions, invalidator: RecordingInvalidator
) -> None:
    first = await create(service, session_factory, cash())
    second = await create(service, session_factory, cash(amount="-1.00"))
    await delete(service, session_factory, first)
    before = await fetch(
        session_factory,
        "SELECT deleted_at, deletion_batch_id FROM ledger.entries WHERE id = :id",
        id=first,
    )
    invalidator.calls.clear()

    await delete(service, session_factory, first)
    await delete(service, session_factory, first, second)

    after = await fetch(
        session_factory,
        "SELECT deleted_at, deletion_batch_id FROM ledger.entries WHERE id = :id",
        id=first,
    )
    assert after == before
    batches = await fetch(session_factory, "SELECT DISTINCT deletion_batch_id FROM ledger.entries")
    assert len(batches) == 2
    assert [type(c) for c in invalidator.calls] == [CashMovementsChanged]


async def test_overlapping_deletions_wait_on_the_row_locks(
    service: LedgerService, session_factory: Sessions
) -> None:
    a, b, c = [await create(service, session_factory, cash(amount=f"{n}.00")) for n in (1, 2, 3)]
    first_holds_its_locks, release_first = asyncio.Event(), asyncio.Event()

    class HoldingInvalidator(RecordingInvalidator):
        async def cash_movements_changed(self, effective_date: date, *, uow: UnitOfWork) -> None:
            first_holds_its_locks.set()
            await release_first.wait()

    assets = FakeAssets()
    holding = create_ledger_service(
        clock=FixedClock(TODAY),
        assets=assets,
        pricer=CalculatorPricer(assets),
        invalidator=HoldingInvalidator(),
    )
    first = asyncio.create_task(delete(holding, session_factory, a, b))
    await asyncio.wait_for(first_holds_its_locks.wait(), timeout=5)
    second = asyncio.create_task(delete(service, session_factory, b, c))
    await asyncio.sleep(0.3)
    assert not second.done()  # waiting on b, locked by the first batch

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=10)

    rows = await fetch(session_factory, "SELECT id, deletion_batch_id FROM ledger.entries")
    batch = {row.id: row.deletion_batch_id for row in rows}
    assert batch[a] == batch[b]  # b stays in the first batch
    assert batch[c] not in {None, batch[a]}


async def test_an_execution_price_never_becomes_a_reference_price(
    service: LedgerService, session_factory: Sessions
) -> None:
    await create(service, session_factory, trade())
    await create(
        service,
        session_factory,
        trade(date(2026, 10, 15), rate="0.093203413834", contract_id=DI1F29.id),
    )

    assert await fetch(session_factory, "SELECT id FROM prices.reference_prices") == []


async def test_a_rejected_entry_writes_nothing(
    service: LedgerService, session_factory: Sessions, invalidator: RecordingInvalidator
) -> None:
    with pytest.raises(DomainError):
        await create(service, session_factory, trade(date(2026, 10, 19)))

    assert await fetch(session_factory, "SELECT id FROM ledger.entries") == []
    assert invalidator.calls == []


class _ReadOnly:
    """A Unit of Work over a plain session for the list read, which never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def commit(self) -> None:
        raise AssertionError("a read never commits")
