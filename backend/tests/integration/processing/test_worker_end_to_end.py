"""The worker with the real collaborators on PostgreSQL: Ledger's, Prices', Asset's and
Portfolio's readers and Portfolio's writer, all on the date's session (plan §7: both chains of an
ALL date in one transaction; the Carteira's AUM, computed on read as ``cash + market value``,
after CASH-only, POSITIONS-only and ALL publishes; missing price). Expected values by hand from
CLAUDE.md §2."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.ledger.dependencies import build_ledger_reader
from di1.modules.portfolio.dependencies import (
    portfolio_query_service,
    portfolio_reader,
    results_writer,
)
from di1.modules.prices.dependencies import build_price_reader
from di1.modules.processing.dependencies import make_date_status_reader, make_range_processor
from di1.platform.database.unit_of_work import unit_of_work_factory
from tests.fakes.clock import FixedClock
from tests.integration.processing.worker_support import MutableClock
from tests.support.builders import DI1F29
from tests.support.db import seed_catalogue

D1, D2, D3 = date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)


class RealWorker:
    def __init__(self, engine: AsyncEngine, factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.clock = MutableClock()
        uow_factory = unit_of_work_factory(factory)
        self.uow_factory = uow_factory
        self.processor = make_range_processor(  # the worker's wiring
            uow_factory=uow_factory,
            clock=self.clock,
            ledger_reader=build_ledger_reader,
            price_reader=build_price_reader,
            asset_reader=build_asset_reader,
            portfolio_reader=portfolio_reader,
            writer=results_writer(),
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
        await self.processor.sweep()  # the run message is not relayed here
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT * FROM processing.requests WHERE id = :id"), {"id": request_id}
                )
            ).one()
        return dict(row._mapping)

    async def aum(self, *days: date) -> list[Decimal | None]:
        """Each date's AUM as the Carteira summary reads it (computed on read, OQ-21, OQ-38)."""
        found = []
        for day in days:
            async with self.uow_factory() as uow:
                summary = await portfolio_query_service(
                    uow,
                    assets=build_asset_reader(uow.session),
                    prices=build_price_reader(uow.session),
                    date_statuses=make_date_status_reader(),
                    clock=FixedClock(D3),
                ).get_summary(day)
            found.append(summary.aum)
        return found

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
    seed_catalogue(real.engine, (DI1F29,))
    asset = DI1F29.id
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
        "SELECT metric_date, positions_market_value, daily_pnl, cumulative_pnl"
        " FROM portfolio.portfolio_metrics ORDER BY 1"
    ) == [
        (D1, Decimal("951000"), Decimal("1000"), Decimal("1000")),
        (D2, Decimal("952000"), Decimal("1000"), Decimal("2000")),
    ]
    assert await real.aum(D1, D2) == [Decimal("1001000"), Decimal("1002000")]
    assert await real.rows(
        "SELECT date, portfolio, cash FROM processing.date_status ORDER BY 1"
    ) == [(D1, "PROCESSED", "PROCESSED"), (D2, "PROCESSED", "PROCESSED")]


async def test_aum_after_a_cash_only_then_a_positions_only_run(real: RealWorker) -> None:
    await seed_day_one(real)

    await real.process("CASH", D1, D2)
    # The positions chain is not processed: no AUM yet (OQ-38).
    assert await real.aum(D1, D2) == [None, None]

    await real.process("POSITIONS", D1, D2)
    assert await real.aum(D1, D2) == [Decimal("1001000"), Decimal("1002000")]


async def test_aum_after_a_positions_only_run_without_cash_is_null(real: RealWorker) -> None:
    await seed_day_one(real)

    await real.process("POSITIONS", D1, D1)

    assert await real.rows(
        "SELECT metric_date, positions_market_value FROM portfolio.portfolio_metrics"
    ) == [(D1, Decimal("951000"))]
    assert await real.aum(D1) == [None]


async def test_a_missing_price_publishes_quantities_and_cash_with_null_figures(
    real: RealWorker,
) -> None:
    asset = await seed_day_one(real, price_d2=False)

    run = await real.process("ALL", D1, D2)

    assert run["status"] == "COMPLETED_WITH_ISSUES"
    assert await real.rows(
        "SELECT metric_date, positions_market_value, daily_pnl, cumulative_pnl,"
        " valuation_status, pnl_status FROM portfolio.portfolio_metrics"
        " WHERE metric_date = '2026-10-07'"
    ) == [(D2, None, None, None, "MISSING", "MISSING")]
    assert await real.aum(D2) == [None]
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


async def fail_cash_writes_on(real: RealWorker, day: date) -> None:
    """A real SQL error inside the cash chain's savepoint: a trigger refuses D's cash row."""
    await real.sql(
        "CREATE FUNCTION public.refuse_cash() RETURNS trigger LANGUAGE plpgsql AS $$"
        " BEGIN RAISE EXCEPTION 'cash refused on %', NEW.balance_date; END $$"
    )
    await real.sql(
        "CREATE TRIGGER refuse_cash BEFORE INSERT OR UPDATE ON portfolio.cash_balances"
        f" FOR EACH ROW WHEN (NEW.balance_date = DATE '{day.isoformat()}')"
        " EXECUTE FUNCTION public.refuse_cash()"
    )


async def test_a_sql_error_in_the_cash_savepoint_keeps_positions_of_the_date(
    real: RealWorker,
) -> None:
    await seed_day_one(real)
    await fail_cash_writes_on(real, D2)

    run = await real.process("ALL", D1, D2)

    assert await real.rows(
        "SELECT date, portfolio, cash FROM processing.date_status ORDER BY 1"
    ) == [(D1, "PROCESSED", "PROCESSED"), (D2, "PROCESSED", "FAILED")]
    assert (run["status"], run["failed_date"], run["failed_chain"], run["progress_date"]) == (
        "COMPLETED_WITH_ISSUES",
        D2,
        "CASH",
        D2,
    )
    assert await real.rows("SELECT balance_date FROM portfolio.cash_balances ORDER BY 1") == [(D1,)]
    assert await real.rows("SELECT metric_date FROM portfolio.portfolio_metrics ORDER BY 1") == [
        (D1,),
        (D2,),
    ]


async def test_case_18_aum_is_null_from_the_failed_date_on(real: RealWorker) -> None:
    await seed_day_one(real)
    await real.sql(
        "INSERT INTO prices.reference_prices (asset_id, reference_date, source, input_kind, pu)"
        " SELECT asset_id, DATE '2026-10-08', 'B3', 'PU', 95300 FROM prices.reference_prices"
        " WHERE reference_date = :d",
        d=D2,
    )
    await fail_cash_writes_on(real, D2)

    await real.process("ALL", D1, D3)

    # D1 has both chains; from D2 the cash chain is FAILED, then not processed: AUM null.
    assert await real.rows(
        "SELECT metric_date, positions_market_value FROM portfolio.portfolio_metrics ORDER BY 1"
    ) == [(D1, Decimal("951000")), (D2, Decimal("952000")), (D3, Decimal("953000"))]
    assert await real.aum(D1, D2, D3) == [Decimal("1001000"), None, None]


async def test_a_d_minus_1_price_corrected_after_processing_changes_no_status(
    real: RealWorker,
) -> None:
    await seed_day_one(real)
    await real.process("POSITIONS", D1, D2)
    before = await real.rows(
        "SELECT date, portfolio, portfolio_processed_at FROM processing.date_status ORDER BY 1"
    )
    figures = await real.rows(
        "SELECT metric_date, daily_pnl FROM portfolio.portfolio_metrics ORDER BY 1"
    )

    await real.sql(
        "UPDATE prices.reference_prices SET pu = 95150, updated_at = now()"
        " WHERE reference_date = :d",
        d=D1,
    )

    assert before == [
        (D1, "PROCESSED", before[0][2]),
        (D2, "PROCESSED", before[1][2]),
    ]
    assert (
        await real.rows(
            "SELECT date, portfolio, portfolio_processed_at FROM processing.date_status ORDER BY 1"
        )
        == before
    )  # no staleness (OQ-31): the dates keep their status until reprocessed
    assert (
        await real.rows("SELECT metric_date, daily_pnl FROM portfolio.portfolio_metrics ORDER BY 1")
        == figures
    )
