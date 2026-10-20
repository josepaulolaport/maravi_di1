"""The worker against PostgreSQL: Processing's real persistence, in-memory readers of the other
modules, and a writer that writes its calls into a scratch table in the date's transaction, so a
rolled-back savepoint or date leaves no row."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

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
from di1.modules.processing.application.ports import RUN_MESSAGE_TYPE, ChainPorts, RunPorts
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.application.services.processing import ProcessingPreview
from di1.modules.processing.application.services.run_processor import PortfolioRangeProcessor
from di1.modules.processing.dependencies import build_date_status_reader
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
    SqlIssueRepository,
    SqlRequestRepository,
    savepoint,
)
from di1.modules.processing.presentation.messaging.run_message import RunMessageHandler
from di1.modules.processing.public import DateStatus, ProcessingRequest, ProcessingScope
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from di1.platform.messaging.envelope import Envelope
from di1.shared.clock import SAO_PAULO, Clock
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
    """Writes ``(day, chain)`` into ``public.test_writes`` on the date's session (`on`), then runs
    ``hook`` (which may raise to simulate a failure)."""

    world: World
    hook: Hook | None = None
    fail: set[tuple[str, date]] = field(default_factory=set)

    def on(self, session: AsyncSession) -> SessionWriter:
        return SessionWriter(self, session)


@dataclass
class SessionWriter:
    """`PortfolioResultsWriter` on one session, as ``build_results_writer`` builds it."""

    table: TableWriter
    session: AsyncSession

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        await self._write("POSITIONS", day.date)
        self.table.world.portfolio.positions[day.date] = PreviousPositionsDay(
            day.closing_state(), pnl.cumulative_pnl
        )

    async def write_cash_day(self, day: CashDay) -> None:
        await self._write("CASH", day.date)
        self.table.world.portfolio.cash[day.date] = day.closing_balance()

    async def _write(self, chain: str, day: date) -> None:
        await self.session.execute(
            text("INSERT INTO public.test_writes (day, chain) VALUES (:d, :c)"),
            {"d": day, "c": chain},
        )
        if self.table.hook is not None:
            await self.table.hook(chain, day)
        if (chain, day) in self.table.fail:
            raise RuntimeError(f"{chain} writer failed on {day}")


@dataclass
class Faults:
    """Faults injected into the run's persistence: the next ``end_failures`` writes of a finished
    run fail as a database blip would (transient), then the next ``end_bugs`` as a bug would (the
    same on every try); the step's transaction then rolls back. ``end_attempts`` counts those
    writes. The date transaction numbered ``fail_on_date_transaction`` fails outside the chains."""

    end_failures: int = 0
    end_bugs: int = 0
    end_attempts: int = 0
    fail_on_date_transaction: int | None = None
    date_transactions: int = 0


class FlakyRequests(SqlRequestRepository):
    def __init__(self, session: AsyncSession, faults: Faults) -> None:
        super().__init__(session)
        self._faults = faults

    async def save(self, request: ProcessingRequest) -> None:
        faults = self._faults
        if request.status.is_finished:
            faults.end_attempts += 1
            if faults.end_failures > 0:
                faults.end_failures -= 1
                raise OperationalError("UPDATE processing.requests", {}, Exception("database blip"))
            if faults.end_bugs > 0:
                faults.end_bugs -= 1
                raise ValueError("bug while ending the run")
        await super().save(request)


class FlakyDateStatuses(SqlDateStatusRepository):
    def __init__(self, session: AsyncSession, clock: Clock, faults: Faults) -> None:
        super().__init__(session, clock)
        self._faults = faults

    async def lock_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        """D's transaction locks D−1 and D first, outside every chain's savepoint."""
        if start_date < end_date:
            self._faults.date_transactions += 1
            if self._faults.date_transactions == self._faults.fail_on_date_transaction:
                raise RuntimeError("failure outside the chains")
        return await super().lock_range(start_date, end_date)


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
        self.faults = Faults()
        self.uow_factory = unit_of_work_factory(session_factory)
        # The preview reads the same Ledger as the run, so the two can be compared.
        self.service = make_service(clock=self.clock, history=LedgerChainHistory(self.world.ledger))
        self.processor = PortfolioRangeProcessor(
            uow_factory=self.uow_factory,
            ports_for=self._ports,
            clock=self.clock,
            end_retry_delays=END_RETRY_DELAYS,
        )

    def _ports(self, uow: UnitOfWork) -> RunPorts:
        """Processing's real persistence, the in-memory world for the other modules."""
        session = uow.session
        return RunPorts(
            requests=FlakyRequests(session, self.faults),
            date_statuses=FlakyDateStatuses(session, self.clock, self.faults),
            issues=SqlIssueRepository(session, self.clock),
            history=LedgerChainHistory(self.world.ledger),
            chains=ChainPorts(
                ledger=self.world.ledger,
                prices=self.world.prices,
                assets=self.world.instruments,
                portfolio=self.world.portfolio,
                writer=self.writer.on(session),
            ),
            savepoint=lambda: savepoint(session),
        )

    async def setup(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE TABLE public.test_writes (day DATE, chain TEXT)"))

    async def enqueue(self, scope: str, start: date, end: date) -> UUID:
        """Queues a request through `ProcessingService`, which publishes its run message."""
        self.clock.advance(1)
        async with self.uow_factory() as uow:
            request = await self.service.on(uow).enqueue_range(ProcessingScope(scope), start, end)
        return request.id

    async def preview(self, scope: str, start: date, end: date) -> ProcessingPreview:
        """`ProcessingService.preview_range`, in its own transaction."""
        async with self.uow_factory() as uow:
            return await self.service.on(uow).preview_range(ProcessingScope(scope), start, end)

    async def cancel(self, request_id: UUID) -> None:
        """`ProcessingService.request_cancel`, in its own transaction."""
        async with self.uow_factory() as uow:
            await self.service.on(uow).request_cancel(request_id)

    async def deliver(self, request_id: UUID) -> bool:
        """The worker handles ``request_id``'s run message through the real handler: it takes
        the oldest QUEUED request and runs it (OQ-50 item 2); `False` when the message starts
        nothing (nothing QUEUED, or a run is RUNNING)."""
        run = await RunMessageHandler(self.processor)(
            Envelope(
                message_id=uuid4(),
                message_type=RUN_MESSAGE_TYPE,
                schema_version=1,
                created_at=self.clock.now(),
                payload={"request_id": str(request_id)},
            )
        )
        if run is None:
            return False
        await run()
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

    async def all_runs(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM processing.requests ORDER BY created_at, id")
            )
            return [dict(row._mapping) for row in result]

    async def statuses(self) -> dict[date, tuple[str | None, str | None]]:
        """``{date: (portfolio, cash)}``."""
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT date, portfolio, cash FROM processing.date_status ORDER BY date")
            )
            return {row[0]: (row[1], row[2]) for row in result}

    async def displayed(self, start: date, end: date) -> dict[date, tuple[str | None, str | None]]:
        """``{date: (portfolio, cash)}`` as a read shows them (`DateStatusReader`), "Processando"
        derived for the active run's current date (OQ-50 item 4)."""
        async with self.uow_factory() as uow:
            statuses = await build_date_status_reader(uow.session, self.clock).get_date_statuses(
                start, end
            )
        return {
            day: (
                None if s.portfolio is None else s.portfolio.value,
                None if s.cash is None else s.cash.value,
            )
            for day, s in statuses.items()
        }

    async def status_rows(self) -> dict[date, dict[str, Any]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM processing.date_status"))
            return {row.date: dict(row._mapping) for row in result}

    async def writes(self) -> list[tuple[date, str]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT day, chain FROM public.test_writes ORDER BY day, chain")
            )
            return [(row[0], row[1]) for row in result]

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
