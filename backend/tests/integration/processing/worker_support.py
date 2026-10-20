"""The worker against PostgreSQL: Processing's real persistence, in-memory readers of the other
modules, and a writer that writes its calls into a scratch table in the date's transaction, so a
rolled-back savepoint or date leaves no row."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.pnl.public import AssetPnLResult, PortfolioPnLResult
from di1.modules.portfolio.public import (
    CashDay,
    PortfolioValuation,
    PositionsDay,
    PreviousPositionsDay,
)
from di1.modules.processing.application.services.chain_history import ChainHistory
from di1.modules.processing.application.services.processing import ProcessingPreview
from di1.modules.processing.application.services.run_chains import DayReaders
from di1.modules.processing.application.services.run_processor import (
    FINISHED,
    PortfolioRangeProcessor,
)
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
)
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.modules.processing.public import ProcessingRequest, ProcessingScope
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.shared.clock import SAO_PAULO
from tests.integration.processing.support import make_service
from tests.unit.processing.run_fakes import World

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=SAO_PAULO)


@dataclass
class MutableClock:
    current: datetime = T0

    def today(self) -> date:
        return self.current.date()

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


Hook = Callable[[str, date], Awaitable[None]]


@dataclass
class TableWriter:
    """Writes ``(day, chain, other_chain_processed)`` into ``public.test_writes`` on the
    caller's Unit of Work, then runs ``hook`` (which may raise to simulate a failure)."""

    world: World
    hook: Hook | None = None
    fail: set[tuple[str, date]] = field(default_factory=set)

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
        *,
        uow: UnitOfWork,
        other_chain_processed: bool,
    ) -> None:
        await self._write("POSITIONS", day.date, other_chain_processed, uow)
        self.world.portfolio.positions[day.date] = PreviousPositionsDay(
            day.closing_state(), pnl.cumulative_pnl
        )

    async def write_cash_day(
        self, day: CashDay, *, uow: UnitOfWork, other_chain_processed: bool
    ) -> None:
        await self._write("CASH", day.date, other_chain_processed, uow)
        self.world.portfolio.cash[day.date] = day.closing_balance()

    async def _write(self, chain: str, day: date, other: bool, uow: UnitOfWork) -> None:
        await uow.session.execute(
            text("INSERT INTO public.test_writes (day, chain, other) VALUES (:d, :c, :o)"),
            {"d": day, "c": chain, "o": other},
        )
        if self.hook is not None:
            await self.hook(chain, day)
        if (chain, day) in self.fail:
            raise RuntimeError(f"{chain} writer failed on {day}")


class FlakyRunStore(SqlRunStore):
    """`SqlRunStore` whose writes of a finished run fail: the next ``end_failures`` as a
    database blip would (transient), then the next ``end_bugs`` as a bug would (the same on
    every try). The step's transaction then rolls back. ``end_attempts`` counts the writes."""

    end_failures = 0
    end_bugs = 0
    end_attempts = 0

    async def save_run(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        if request.status in FINISHED:
            self.end_attempts += 1
            if self.end_failures > 0:
                self.end_failures -= 1
                raise OperationalError("UPDATE processing.requests", {}, Exception("database blip"))
            if self.end_bugs > 0:
                self.end_bugs -= 1
                raise ValueError("bug while ending the run")
        await super().save_run(request, uow=uow)


END_RETRY_DELAYS = (0.0, 0.0)
"""Two retries without a pause: three attempts at the end of a run."""


class Worker:
    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        world: World | None = None,
    ) -> None:
        self.engine = engine
        self.clock = MutableClock()
        self.world = world or World()
        self.writer = TableWriter(self.world)
        self.fail_reading_on_date_transaction: int | None = None
        self._date_transactions = 0
        self.uow_factory = unit_of_work_factory(session_factory)
        self.store = FlakyRunStore(self.clock)
        # The preview reads the same Ledger as the run, so the two can be compared.
        self.service = make_service(clock=self.clock, history=ChainHistory(self.world.ledger))
        self.processor = PortfolioRangeProcessor(
            uow_factory=self.uow_factory,
            store=self.store,
            date_statuses=SqlDateStatusRepository(),
            readers_for=self._readers,
            writer=self.writer,
            clock=self.clock,
            end_retry_delays=END_RETRY_DELAYS,
        )

    def _readers(self, uow: UnitOfWork) -> DayReaders:
        """Built once per date transaction, outside every chain's savepoint."""
        self._date_transactions += 1
        if self._date_transactions == self.fail_reading_on_date_transaction:
            raise RuntimeError("failure outside the chains")
        return self.world.readers(uow)

    async def setup(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE public.test_writes (day DATE, chain TEXT, other BOOLEAN)")
            )

    async def enqueue(self, scope: str, start: date, end: date) -> UUID:
        """Queues a request through `ProcessingService`, which publishes its run message."""
        self.clock.advance(1)
        async with self.uow_factory() as uow:
            request = await self.service.enqueue_range(ProcessingScope(scope), start, end, uow=uow)
        return request.id

    async def preview(self, scope: str, start: date, end: date) -> ProcessingPreview:
        """`ProcessingService.preview_range`, in its own transaction."""
        async with self.uow_factory() as uow:
            return await self.service.preview_range(ProcessingScope(scope), start, end, uow=uow)

    async def cancel(self, request_id: UUID) -> None:
        """`ProcessingService.request_cancel`, in its own transaction."""
        async with self.uow_factory() as uow:
            await self.service.request_cancel(request_id, uow=uow)

    async def deliver(self, request_id: UUID) -> bool:
        """The worker handles ``request_id``'s run message: it starts that request, then runs
        it; `False` when the message is skipped (the request is not QUEUED, or a run is)."""
        if not await self.processor.start(request_id):
            return False
        await self.processor.run(request_id)
        return True

    async def sweep(self) -> None:
        """The worker's periodic sweep: it runs the QUEUED requests, oldest first."""
        await self.processor.sweep()

    async def take_next(self) -> UUID | None:
        """The worker takes the oldest QUEUED request (RUNNING) without running it yet."""
        return await self.processor.take_next()

    async def restart(self) -> None:
        """The worker starts again: it recovers the interrupted run, then sweeps the queue
        (OQ-45)."""
        await self.processor.recover_at_startup()

    async def run_row(self, request_id: UUID) -> dict[str, Any]:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT * FROM processing.requests WHERE id = :id"), {"id": request_id}
                )
            ).one()
            return dict(row._mapping)

    async def statuses(self) -> dict[date, tuple[str | None, str | None]]:
        """``{date: (portfolio, cash)}``."""
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT date, portfolio, cash FROM processing.date_status ORDER BY date")
            )
            return {row[0]: (row[1], row[2]) for row in result}

    async def status_rows(self) -> dict[date, dict[str, Any]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM processing.date_status"))
            return {row.date: dict(row._mapping) for row in result}

    async def writes(self) -> list[tuple[date, str, bool]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT day, chain, other FROM public.test_writes ORDER BY day, chain")
            )
            return [(row[0], row[1], row[2]) for row in result]

    async def outbox(self) -> list[tuple[str, dict[str, Any]]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT message_type, payload FROM platform.outbox_messages ORDER BY id")
            )
            return [(row[0], row[1]) for row in result]

    async def issues(self) -> list[tuple[str, date, date | None]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT issue_type, affected_date, required_price_date FROM processing.issues"
                    " ORDER BY affected_date, issue_type"
                )
            )
            return [(row[0], row[1], row[2]) for row in result]

    async def wait_for_a_lock_waiter(self, count: int = 1) -> None:
        """Returns once ``count`` other sessions of this database wait on a lock (the cancel
        queued behind the run's row lock); fails after 5 seconds."""
        async with asyncio.timeout(5):
            while True:
                async with self.engine.connect() as connection:
                    waiting = await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity"
                            " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        )
                    )
                if waiting >= count:
                    return
                await asyncio.sleep(0.01)

    async def execute(self, statement: str, **params: Any) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text(statement), params)
