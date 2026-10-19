"""The worker against PostgreSQL: Processing's real persistence, in-memory readers of the other
modules, and a writer that writes its calls into a scratch table in the date's transaction, so a
rolled-back savepoint or date leaves no row."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.pnl.public import AssetPnLResult, PortfolioPnLResult
from di1.modules.portfolio.public import (
    CashDay,
    PortfolioValuation,
    PositionsDay,
    PreviousPositionsDay,
)
from di1.modules.processing.application.services.dispatcher import ProcessingDispatcher
from di1.modules.processing.application.services.run_chains import DayReaders
from di1.modules.processing.application.services.run_processor import (
    Claim,
    PortfolioRangeProcessor,
)
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
)
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.shared.clock import SAO_PAULO
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
        store = SqlRunStore(self.clock)
        self.dispatcher = ProcessingDispatcher(
            uow_factory=self.uow_factory, store=store, clock=self.clock
        )
        self.processor = PortfolioRangeProcessor(
            uow_factory=self.uow_factory,
            store=store,
            date_statuses=SqlDateStatusRepository(),
            readers_for=self._readers,
            writer=self.writer,
            clock=self.clock,
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
        request_id = uuid.uuid4()
        self.clock.advance(1)
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO processing.requests (id, scope, start_date, end_date,"
                    " created_at, updated_at) VALUES (:id, :s, :a, :b, :t, :t)"
                ),
                {"id": request_id, "s": scope, "a": start, "b": end, "t": self.clock.now()},
            )
        return request_id

    async def claim(self, request_id: UUID) -> Claim | None:
        async with self.uow_factory() as uow:
            return await self.processor.claim(request_id, uow=uow)

    async def dispatch_and_run(self) -> UUID:
        """Dispatch the next run, claim it and run it to its end."""
        request_id = await self.dispatcher.dispatch_next()
        assert request_id is not None
        claim = await self.claim(request_id)
        assert claim is not None
        await self.processor.run(claim.request_id)
        return request_id

    async def restart(self) -> None:
        """The worker starts again: it recovers the interrupted run before consuming (OQ-45)."""
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

    async def active_request_id(self) -> UUID | None:
        async with self.engine.connect() as connection:
            value = await connection.scalar(
                text("SELECT active_request_id FROM processing.calculation_state")
            )
            return value if isinstance(value, UUID) else None

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

    async def wait_for_a_lock_waiter(self) -> None:
        """Returns once another session of this database waits on a lock (the cancel queued
        behind the run's row lock); fails after 5 seconds."""
        async with asyncio.timeout(5):
            while True:
                async with self.engine.connect() as connection:
                    waiting = await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity"
                            " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        )
                    )
                if waiting:
                    return
                await asyncio.sleep(0.01)

    async def execute(self, statement: str, **params: Any) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text(statement), params)
