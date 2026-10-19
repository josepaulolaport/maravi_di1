"""`DateStatusReader` on PostgreSQL 16 (interfaces.md "Processing"; OQ-23, OQ-31): each date's
chain statuses and processing times, read in the caller's transaction."""

from __future__ import annotations

from datetime import date, datetime

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
            text("INSERT INTO processing.date_status (date, cash) VALUES ('2026-10-03', 'RUNNING')")
        )
        statuses = await make_date_status_reader().get_date_statuses(
            date(2026, 10, 3), date(2026, 10, 3), uow=uow
        )

    assert statuses[date(2026, 10, 3)].cash is ChainStatus.RUNNING
    assert statuses[date(2026, 10, 3)].portfolio is None
