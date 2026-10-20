"""`DateStatusReader` on PostgreSQL 16 (interfaces.md "Processing"; OQ-23, OQ-31, OQ-50 item 4):
each date's chain statuses and processing times, read in the caller's transaction, with
"Processando" (RUNNING) derived for the chains of the active run on its current date."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.processing.dependencies import make_date_status_reader
from di1.modules.processing.public import ChainStatus, DateStatus
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.clock import SAO_PAULO
from tests.integration.processing.support import seed_statuses

PROCESSED_AT = datetime(2026, 10, 17, 18, 30, tzinfo=SAO_PAULO)


async def test_oq31_reads_each_date_of_the_range_with_its_processing_times(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_statuses(
        engine,
        {
            date(2026, 10, 1): ("PROCESSED", "PROCESSED"),
            date(2026, 10, 2): ("PROCESSED_WITH_ISSUES", None),
            date(2026, 10, 4): ("FAILED", "PROCESSED"),
            date(2026, 10, 9): ("PROCESSED", "PROCESSED"),
        },
        processed_at=PROCESSED_AT,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        statuses = await make_date_status_reader().get_date_statuses(
            date(2026, 10, 2), date(2026, 10, 5), uow=uow
        )

    assert statuses == {
        date(2026, 10, 2): DateStatus(
            date=date(2026, 10, 2),
            portfolio=ChainStatus.PROCESSED_WITH_ISSUES,
            cash=None,
            portfolio_processed_at=PROCESSED_AT,
            cash_processed_at=None,
        ),
        date(2026, 10, 4): DateStatus(
            date=date(2026, 10, 4),
            portfolio=ChainStatus.FAILED,
            cash=ChainStatus.PROCESSED,
            portfolio_processed_at=PROCESSED_AT,
            cash_processed_at=PROCESSED_AT,
        ),
    }


async def test_the_read_sees_the_callers_own_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO processing.date_status (date, cash) VALUES ('2026-10-03', 'PROCESSED')"
            )
        )
        statuses = await make_date_status_reader().get_date_statuses(
            date(2026, 10, 3), date(2026, 10, 3), uow=uow
        )

    assert statuses[date(2026, 10, 3)].cash is ChainStatus.PROCESSED
    assert statuses[date(2026, 10, 3)].portfolio is None


D1, D2, D3 = date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)


async def _run(
    engine: AsyncEngine,
    scope: str,
    status: str = "RUNNING",
    *,
    progress_date: date | None = None,
    failed_chain: str | None = None,
) -> UUID:
    """A run of [D1, D3] in ``status``, as the worker leaves it between two dates."""
    request_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO processing.requests (id, scope, start_date, end_date, status,"
                " progress_date, failed_date, failed_chain, created_at, updated_at)"
                " VALUES (:id, :scope, :start, :end, :status, :progress, :failed_date,"
                " :failed_chain, now(), now())"
            ),
            {
                "id": request_id,
                "scope": scope,
                "start": D1,
                "end": D3,
                "status": status,
                "progress": progress_date,
                "failed_date": None if failed_chain is None else D1,
                "failed_chain": failed_chain,
            },
        )
    return request_id


async def _read(
    session_factory: async_sessionmaker[AsyncSession], start: date = D1, end: date = D3
) -> dict[date, tuple[ChainStatus | None, ChainStatus | None]]:
    """``{date: (portfolio, cash)}`` as the reader shows them."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        statuses = await make_date_status_reader().get_date_statuses(start, end, uow=uow)
    return {day: (status.portfolio, status.cash) for day, status in statuses.items()}


async def test_oq50_the_active_runs_current_date_reads_processando_over_its_old_status(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_statuses(
        engine, {D1: (None, "PROCESSED"), D2: ("PROCESSED", "FAILED")}, processed_at=PROCESSED_AT
    )
    await _run(engine, "CASH", progress_date=D1)

    assert await _read(session_factory) == {
        D1: (None, ChainStatus.PROCESSED),
        D2: (ChainStatus.PROCESSED, ChainStatus.RUNNING),  # stored FAILED, being reprocessed
    }
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        d2 = (await make_date_status_reader().get_date_statuses(D2, D2, uow=uow))[D2]
    assert d2.cash_processed_at == PROCESSED_AT  # the last commit's time is kept


async def test_oq50_a_run_with_no_progress_reads_processando_on_its_start_date(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _run(engine, "ALL")

    assert await _read(session_factory) == {D1: (ChainStatus.RUNNING, ChainStatus.RUNNING)}
    assert await _read(session_factory, D2, D3) == {}  # outside the range read


async def test_oq50_on_an_all_run_only_the_chain_still_alive_reads_processando(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_statuses(engine, {D1: ("PROCESSED", "FAILED")}, processed_at=PROCESSED_AT)
    await _run(engine, "ALL", progress_date=D1, failed_chain="CASH")

    assert await _read(session_factory) == {
        D1: (ChainStatus.PROCESSED, ChainStatus.FAILED),
        D2: (ChainStatus.RUNNING, None),
    }


@pytest.mark.parametrize(
    ("status", "progress_date"),
    [("QUEUED", None), ("COMPLETED", D3), ("CANCELLED", D1), ("FAILED", None), ("RUNNING", D3)],
)
async def test_oq50_no_date_reads_processando_without_a_run_on_a_date(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
    progress_date: date | None,
) -> None:
    # A RUNNING run whose progress is its end date is only recording its end.
    await _run(engine, "CASH", status, progress_date=progress_date)

    assert await _read(session_factory) == {}
