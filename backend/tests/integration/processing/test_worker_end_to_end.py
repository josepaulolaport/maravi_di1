"""The worker with the real collaborators on PostgreSQL: Ledger's, Prices', Asset's and
Portfolio's readers and Portfolio's writer, all on the date's session (plan §7: both chains and
the AUM of an ALL date in one transaction; ``aum = cash + market value`` after CASH-only,
POSITIONS-only and ALL publishes; missing price). Expected values by hand from CLAUDE.md §2."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import asset_reader
from di1.modules.ledger.dependencies import ledger_reader
from di1.modules.portfolio.dependencies import portfolio_reader, results_writer
from di1.modules.prices.dependencies import price_reader
from di1.modules.processing.application.services.dispatcher import ProcessingDispatcher
from di1.modules.processing.application.services.run_chains import DayReaders
from di1.modules.processing.application.services.run_processor import PortfolioRangeProcessor
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
)
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.platform.database.unit_of_work import UnitOfWork, unit_of_work_factory
from tests.integration.processing.support import seed_instrument
from tests.integration.processing.worker_support import MutableClock

D1, D2 = date(2026, 10, 6), date(2026, 10, 7)


def readers_for(uow: UnitOfWork) -> DayReaders:
    return DayReaders(
        ledger=ledger_reader(uow.session),
        prices=price_reader(uow.session),
        assets=asset_reader(uow.session),
        portfolio=portfolio_reader(uow.session),
    )


class RealWorker:
    def __init__(self, engine: AsyncEngine, factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.clock = MutableClock()
        uow_factory = unit_of_work_factory(factory)
        store = SqlRunStore(self.clock)
        self.uow_factory = uow_factory
        self.dispatcher = ProcessingDispatcher(
            uow_factory=uow_factory, store=store, clock=self.clock
        )
        self.processor = PortfolioRangeProcessor(
            uow_factory=uow_factory,
            store=store,
            date_statuses=SqlDateStatusRepository(),
            readers_for=readers_for,
            writer=results_writer(),
            clock=self.clock,
        )

    async def sql(self, statement: str, **params: Any) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text(statement), params)

    async def process(self, scope: str, start: date, end: date) -> dict[str, Any]:
        self.clock.advance(1)
        async with self.engine.begin() as connection:
            request_id = await connection.scalar(
                text(
                    "INSERT INTO processing.requests (scope, start_date, end_date, created_at,"
                    " updated_at) VALUES (:s, :a, :b, :t, :t) RETURNING id"
                ),
                {"s": scope, "a": start, "b": end, "t": self.clock.now()},
            )
        assert await self.dispatcher.dispatch_next() == request_id
        async with self.uow_factory() as uow:
            claim = await self.processor.claim(request_id, uow=uow)
        assert claim is not None
        await self.processor.run(claim.request_id, claim.token)
        await self.dispatcher.dispatch_next()  # frees the slot
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT * FROM processing.requests WHERE id = :id"), {"id": request_id}
                )
            ).one()
        return dict(row._mapping)

    async def rows(self, query: str) -> list[tuple[Any, ...]]:
        async with self.engine.connect() as connection:
            return [tuple(row) for row in await connection.execute(text(query))]


@pytest.fixture
async def real(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[RealWorker]:
    yield RealWorker(engine, session_factory)


async def seed_day_one(real: RealWorker, *, price_d2: bool = True) -> UUID:
    """Deposit 1 000 000 and buy 10 DI1F29 at 95 000 on D1; B3 prices 95 100 (D1), 95 200 (D2)."""
    asset = await seed_instrument(real.engine, "DI1F29")
    await real.sql(
        "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount)"
        " VALUES ('CASH', :d, '09:00', 1000000.00)",
        d=D1,
    )
    await real.sql(
        "INSERT INTO ledger.entries (type, entry_date, entry_time, asset_id, signed_quantity,"
        " execution_pu, execution_rate, input_kind)"
        " VALUES ('TRADE', :d, '10:00', :a, 10, 95000.0000000000, 0.1, 'PU')",
        d=D1,
        a=asset,
    )
    prices = [(D1, "95100.0000000000")] + ([(D2, "95200.0000000000")] if price_d2 else [])
    for day, pu in prices:
        await real.sql(
            "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu)"
            " VALUES (:a, :d, 'B3', 'PU', :pu)",
            a=asset,
            d=day,
            pu=Decimal(pu),
        )
    return asset


async def test_an_all_run_publishes_both_chains_and_the_aum(real: RealWorker) -> None:
    await seed_day_one(real)

    run = await real.process("ALL", D1, D2)

    assert run["status"] == "COMPLETED"
    assert await real.rows(
        "SELECT balance_date, cash_balance FROM portfolio.cash_balances ORDER BY 1"
    ) == [(D1, Decimal("50000")), (D2, Decimal("50000"))]
    # cash 50 000 + 10 × 95 100 = 1 001 000; then 50 000 + 10 × 95 200 = 1 002 000
    assert await real.rows(
        "SELECT metric_date, positions_market_value, aum, daily_pnl, cumulative_pnl"
        " FROM portfolio.portfolio_metrics ORDER BY 1"
    ) == [
        (D1, Decimal("951000"), Decimal("1001000"), Decimal("1000"), Decimal("1000")),
        (D2, Decimal("952000"), Decimal("1002000"), Decimal("1000"), Decimal("2000")),
    ]
    assert await real.rows(
        "SELECT date, portfolio, cash FROM processing.date_status ORDER BY 1"
    ) == [(D1, "PROCESSED", "PROCESSED"), (D2, "PROCESSED", "PROCESSED")]


async def test_aum_after_a_cash_only_then_a_positions_only_run(real: RealWorker) -> None:
    await seed_day_one(real)

    await real.process("CASH", D1, D2)
    # The positions chain is not processed: no AUM yet (OQ-38).
    assert await real.rows("SELECT metric_date, aum FROM portfolio.portfolio_metrics") == []

    await real.process("POSITIONS", D1, D2)
    assert await real.rows(
        "SELECT metric_date, aum FROM portfolio.portfolio_metrics ORDER BY 1"
    ) == [(D1, Decimal("1001000")), (D2, Decimal("1002000"))]


async def test_aum_after_a_positions_only_run_without_cash_is_null(real: RealWorker) -> None:
    await seed_day_one(real)

    await real.process("POSITIONS", D1, D1)

    assert await real.rows(
        "SELECT metric_date, positions_market_value, aum FROM portfolio.portfolio_metrics"
    ) == [(D1, Decimal("951000"), None)]


async def test_a_missing_price_publishes_quantities_and_cash_with_null_figures(
    real: RealWorker,
) -> None:
    asset = await seed_day_one(real, price_d2=False)

    run = await real.process("ALL", D1, D2)

    assert run["status"] == "COMPLETED_WITH_ISSUES"
    assert await real.rows(
        "SELECT metric_date, positions_market_value, aum, daily_pnl, cumulative_pnl,"
        " valuation_status, pnl_status FROM portfolio.portfolio_metrics"
        " WHERE metric_date = '2026-10-07'"
    ) == [(D2, None, None, None, None, "MISSING", "MISSING")]
    assert await real.rows(
        "SELECT position_date, quantity FROM portfolio.positions WHERE position_date = '2026-10-07'"
    ) == [(D2, 10)]
    assert await real.rows(
        "SELECT cash_balance FROM portfolio.cash_balances WHERE balance_date = '2026-10-07'"
    ) == [(Decimal("50000"),)]
    assert await real.rows(
        "SELECT asset_id, issue_type, affected_date, required_price_date FROM processing.issues"
    ) == [(asset, "MISSING_REFERENCE_PRICE", D2, D2)]
    assert await real.rows(
        "SELECT date, portfolio, cash FROM processing.date_status ORDER BY 1"
    ) == [(D1, "PROCESSED", "PROCESSED"), (D2, "PROCESSED_WITH_ISSUES", "PROCESSED")]
