"""`ProcessingService` on PostgreSQL 16 (spec §10.2, §13 item 10; plan §5.G, Gate 2):
concurrent enqueue, cancellation, keyset history, issues. The preview's predecessor rule is
tested against the run's in ``test_worker.py`` (``AGREEMENT_CASES``)."""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.processing.domain.issues import IssueType
from di1.modules.processing.public import (
    Chain,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.errors import DomainError, ErrorCode
from di1.shared.paging import PageParams
from tests.fakes.clock import FixedClock
from tests.integration.processing.support import (
    ServiceFactory,
    count,
    make_service,
    request_statuses,
    seed_instrument,
)
from tests.unit.processing.fakes import T0, FakeAssets

A, B = date(2026, 10, 1), date(2026, 10, 5)
ALL = ProcessingScope.ALL


async def _enqueue(
    session_factory: async_sessionmaker[AsyncSession],
    service: ServiceFactory,
    start: date = A,
    end: date = B,
) -> ProcessingRequest:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await service.on(uow).enqueue_range(ALL, start, end)


async def _set_status(engine: AsyncEngine, request_id: UUID, status: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE processing.requests SET status = :s WHERE id = :id"),
            {"s": status, "id": request_id},
        )


async def _set_failure(
    engine: AsyncEngine, request_id: UUID, status: str, failed_date: date, chain: str | None
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE processing.requests SET status = :s, failed_date = :d, failed_chain = :c"
                " WHERE id = :id"
            ),
            {"s": status, "d": failed_date, "c": chain, "id": request_id},
        )


@pytest.mark.parametrize(
    ("status", "failed_date", "chain", "expected_chain"),
    [
        pytest.param(
            "COMPLETED_WITH_ISSUES", date(2026, 10, 3), "CASH", Chain.CASH, id="cash failed"
        ),
        pytest.param(
            "COMPLETED_WITH_ISSUES",
            date(2026, 10, 4),
            "POSITIONS",
            Chain.POSITIONS,
            id="positions failed",
        ),
        pytest.param("FAILED", date(2026, 10, 2), None, None, id="a failure of no chain"),
    ],
)
async def test_oq40_a_runs_first_failure_reads_back_in_the_run_and_the_history(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
    failed_date: date,
    chain: str | None,
    expected_chain: Chain | None,
) -> None:
    service = make_service()
    run = await _enqueue(session_factory, service)
    await _set_failure(engine, run.id, status, failed_date, chain)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await service.on(uow).get_request(run.id)
        page = await service.on(uow).list_requests(PageParams(10, None))

    assert (stored.failed_date, stored.failed_chain) == (failed_date, expected_chain)
    assert (page.items[0].failed_date, page.items[0].failed_chain) == (
        failed_date,
        expected_chain,
    )


async def test_oq40_cancelling_a_running_run_keeps_its_first_failure(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The cancel reads the run, changes its status and writes it back: the worker's
    failed_date and failed_chain must survive (OQ-40 item 6)."""
    service = make_service()
    run = await _enqueue(session_factory, service)
    await _set_failure(engine, run.id, "RUNNING", date(2026, 10, 2), "CASH")

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        flagged = await service.on(uow).request_cancel(run.id)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT status, failed_date, failed_chain FROM processing.requests"),
            )
        ).one()

    assert flagged.status is ProcessingStatus.RUNNING  # flagged only (OQ-46)
    assert flagged.cancel_requested_at is not None
    assert tuple(row) == ("RUNNING", date(2026, 10, 2), "CASH")


@pytest.mark.parametrize("cancel", [False, True], ids=["queued", "cancelled while queued"])
async def test_13_10_a_run_reads_back_exactly_as_the_service_returned_it(
    session_factory: async_sessionmaker[AsyncSession], cancel: bool
) -> None:
    """Every column round-trips, timestamps with their offset: an aware ``created_at`` never
    equals a naive one, so ``==`` fails if the offset were lost."""
    service = make_service()
    returned = await _enqueue(session_factory, service)
    if cancel:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            returned = await service.on(uow).request_cancel(returned.id)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await service.on(uow).get_request(returned.id)

    assert stored == returned
    assert stored.status is (ProcessingStatus.CANCELLED if cancel else ProcessingStatus.QUEUED)
    assert stored.created_at.utcoffset() is not None


async def test_13_10_concurrent_overlapping_requests_are_all_queued(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    service = make_service()

    created = await asyncio.gather(*(_enqueue(session_factory, service) for _ in range(10)))

    assert len({r.id for r in created}) == 10
    assert set((await request_statuses(engine)).values()) == {"QUEUED"}
    assert await count(engine, "processing.requests") == 10
    # Each request publishes one run message naming it, in its own transaction.
    async with engine.connect() as connection:
        messages = (
            await connection.execute(
                text("SELECT message_type, payload FROM platform.outbox_messages")
            )
        ).all()
    assert [m.message_type for m in messages] == ["processing.run"] * 10
    assert sorted(m.payload["request_id"] for m in messages) == sorted(str(r.id) for r in created)


async def _cancel(
    session_factory: async_sessionmaker[AsyncSession], service: ServiceFactory, active: UUID
) -> ProcessingRequest:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await service.on(uow).request_cancel(active)


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("QUEUED", ProcessingStatus.CANCELLED),
        ("RUNNING", ProcessingStatus.RUNNING),
    ],
)
async def test_13_10_two_concurrent_cancels_have_one_winner(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
    outcome: ProcessingStatus,
) -> None:
    """The run's row lock orders concurrent cancels: one cancels or flags it, the other finds
    it finished or its cancel already requested and answers 409 (OQ-29, OQ-46)."""
    for _ in range(5):
        service = make_service()
        active = await _enqueue(session_factory, service)
        await _set_status(engine, active.id, status)

        results = await asyncio.gather(
            _cancel(session_factory, service, active.id),
            _cancel(session_factory, service, active.id),
            return_exceptions=True,
        )

        winners = [r for r in results if isinstance(r, ProcessingRequest)]
        losers = [r for r in results if isinstance(r, DomainError)]
        assert [w.status for w in winners] == [outcome]
        assert [loser.code for loser in losers] == [ErrorCode.JOB_NOT_CANCELLABLE]
        assert (await request_statuses(engine))[active.id] == outcome.value


async def test_12_the_history_pages_by_keyset_even_with_equal_creation_times(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    same_instant = make_service(clock=FixedClock(T0.date(), T0))
    created = [await _enqueue(session_factory, same_instant) for _ in range(5)]
    later = await _enqueue(session_factory, make_service())
    expected = [later.id, *sorted((r.id for r in created), reverse=True)]

    seen: list[UUID] = []
    page_sizes: list[int] = []
    cursor: str | None = None
    while True:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            page = await same_instant.on(uow).list_requests(PageParams(2, cursor))
        seen += [r.id for r in page.items]
        page_sizes.append(len(page.items))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert seen == expected
    # 6 runs by 2: the third page is exactly the last one and has no cursor, so no empty
    # fourth page is ever asked for.
    assert page_sizes == [2, 2, 2]


async def test_10_3_issues_are_listed_newest_first_with_asset_codes(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    di1f29 = await seed_instrument(engine, "DI1F29")
    run = await _enqueue(session_factory, make_service())
    async with engine.begin() as connection:
        di1f27 = await connection.scalar(
            text(
                "INSERT INTO asset.instruments (product_id, code, maturity_date)"
                " SELECT product_id, 'DI1F27', DATE '2027-01-04' FROM asset.instruments"
                " WHERE id = :a RETURNING id"
            ),
            {"a": di1f29},
        )
        await connection.execute(
            text(
                "INSERT INTO processing.issues"
                " (request_id, asset_id, affected_date, required_price_date, issue_type)"
                " VALUES (:r, :f29, '2026-10-16', '2026-10-16', 'MISSING_REFERENCE_PRICE'),"
                " (:r, :f27, '2026-10-14', NULL, 'EXPIRED_OPEN_POSITION')"
            ),
            {"r": run.id, "f29": di1f29, "f27": di1f27},
        )
    service = make_service(assets=FakeAssets({di1f29: "DI1F29", di1f27: "DI1F27"}))

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        issues = await service.on(uow).get_issues()

    assert [
        (i.issue_type, i.asset_code, i.affected_date, i.required_price_date) for i in issues
    ] == [
        (IssueType.MISSING_REFERENCE_PRICE, "DI1F29", date(2026, 10, 16), date(2026, 10, 16)),
        (IssueType.EXPIRED_OPEN_POSITION, "DI1F27", date(2026, 10, 14), None),
    ]
    assert {i.request_id for i in issues} == {run.id}


@pytest.mark.parametrize("code", ["SUPERSEDED", "RECOVERY_EXHAUSTED"])
async def test_a_run_ended_with_a_retired_error_code_still_reads_back(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession], code: str
) -> None:
    """Migration 0003 wrote SUPERSEDED and the OQ-43 code wrote RECOVERY_EXHAUSTED; the history
    must still read those runs."""
    service = make_service()
    run = await _enqueue(session_factory, service)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE processing.requests SET status = 'FAILED', error_code = :c WHERE id = :id"
            ),
            {"c": code, "id": run.id},
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        page = await service.on(uow).list_requests(PageParams(10, None))

    assert page.items[0].error_code == code
