"""Portfolio's published rows against PostgreSQL 16: the writer, the previous-day reader and the
repository's reads (OQ-10, OQ-21, OQ-22, OQ-23, OQ-28, OQ-30). What the service computes on
read from these rows (AUM, the P&L range sum) is tested in tests/unit/portfolio/test_queries.py.

Each write runs in its own Unit of Work and is committed by the test, as Processing commits a
date; the writer itself never commits."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import build_asset_reader
from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.dependencies import (
    build_portfolio_reader,
    build_portfolio_service,
    build_results_writer,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import OpenPosition, PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ValuationStatus,
)
from di1.modules.portfolio.infrastructure.persistence.repositories import SqlPortfolioRepository
from di1.modules.portfolio.public import PortfolioService
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.db import Di1Catalogue
from tests.support.fakes import FakeClock, FakeDateStatusReader, FakePriceReader

COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING
D = date(2026, 10, 15)


def _position(asset_id: UUID, quantity: int, pu: str | None = "89006.4625467350") -> PositionDay:
    trade = Trade(
        asset_id, D, time(10), 1, quantity or 1, Decimal("89006.4625467350"), Decimal("0.1")
    )
    return PositionDay(
        asset_id=asset_id,
        previous_quantity=0,
        quantity=quantity,
        average_entry_pu=None if pu is None else Decimal(pu),
        average_entry_rate=None if pu is None else Decimal("0.100000000000"),
        trades=(trade,),
    )


def _valued(asset_id: UUID, total: str | None, status: ValuationStatus) -> AssetValuation:
    priced = total is not None and status is ValuationStatus.COMPLETE
    return AssetValuation(
        asset_id,
        Decimal("89128.4824345118") if priced else None,
        None if total is None else Decimal(total),
        status,
    )


def _pnl(position: str | None, trades: str | None) -> AssetPnLResult:
    daily = None if position is None or trades is None else Decimal(position) + Decimal(trades)
    return AssetPnLResult(
        None if position is None else Decimal(position),
        None if trades is None else Decimal(trades),
        daily,
        COMPLETE if daily is not None else MISSING,
        frozenset(),
    )


def _portfolio_pnl(daily: str | None, cumulative: str | None) -> PortfolioPnLResult:
    value = None if daily is None else Decimal(daily)
    return PortfolioPnLResult(
        position_pnl=value,
        trades_pnl=None if value is None else Decimal("0"),
        daily_pnl=value,
        cumulative_pnl=None if cumulative is None else Decimal(cumulative),
        status=COMPLETE if value is not None else MISSING,
    )


class Publisher:
    """Writes one chain of one date in its own committed Unit of Work, as Processing does."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def positions(
        self,
        on: date,
        rows: list[tuple[PositionDay, AssetValuation, AssetPnLResult]],
        market_value: str | None,
        pnl: PortfolioPnLResult,
    ) -> None:
        valuation = PortfolioValuation(
            date=on,
            assets=tuple(v for _, v, _ in rows),
            positions_market_value=None if market_value is None else Decimal(market_value),
            status=ValuationStatus.COMPLETE
            if market_value is not None
            else ValuationStatus.MISSING,
        )
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            await build_results_writer(uow.session).write_positions_day(
                PositionsDay(on, tuple(p for p, _, _ in rows)),
                valuation,
                {p.asset_id: r for p, _, r in rows},
                pnl,
            )
            await uow.commit()

    async def cash(self, on: date, balance: str) -> None:
        await self.cash_day(
            CashDay(
                on, Decimal("0"), Decimal("0"), Decimal(balance), Decimal("0"), Decimal(balance)
            )
        )

    async def cash_day(self, day: CashDay) -> None:
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            await build_results_writer(uow.session).write_cash_day(day)
            await uow.commit()


@pytest.fixture
def publish(session_factory: async_sessionmaker[AsyncSession]) -> Publisher:
    return Publisher(session_factory)


def _ids(di1: Di1Catalogue) -> tuple[UUID, UUID]:
    return di1.instrument_ids["DI1F28"], di1.instrument_ids["DI1F29"]


async def test_a_positions_day_reads_back_exactly(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    f28, f29 = _ids(di1)
    await publish.positions(
        D,
        [
            (
                _position(f28, 10),
                _valued(f28, "891284.8243451180", ValuationStatus.COMPLETE),
                _pnl("1220.1988777680", "0"),
            ),
            (
                _position(f29, 5, "82057.00"),
                _valued(f29, None, ValuationStatus.MISSING),
                _pnl(None, "-9254.3334060340"),
            ),
        ],
        None,
        _portfolio_pnl(None, None),
    )

    async with session_factory() as session:
        repository = SqlPortfolioRepository(session)
        rows = {p.asset_id: p for p in await repository.get_positions(D)}
        day = await repository.get_portfolio_day(D)

    assert rows[f28].quantity == 10
    assert rows[f28].average_entry_pu == Decimal("89006.4625467350")
    assert str(rows[f28].average_entry_pu) == "89006.4625467350"  # NUMERIC keeps the scale
    assert rows[f28].financial_total == Decimal("891284.8243451180")
    assert rows[f28].daily_pnl == Decimal("1220.1988777680")
    assert rows[f28].valuation_status is ValuationStatus.COMPLETE
    assert rows[f29].financial_total is None  # null, never zero
    assert rows[f29].position_pnl is None
    assert rows[f29].trades_pnl == Decimal("-9254.3334060340")
    assert rows[f29].daily_pnl is None
    assert rows[f29].valuation_status is ValuationStatus.MISSING
    assert rows[f29].pnl_status is MISSING
    assert day is not None
    assert day.positions_market_value is None
    assert day.valuation_status is MISSING


async def test_a_cash_day_reads_back_exactly_and_a_rewrite_replaces_it(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # 0 − 890064.6254673500 + 1500000.00 − 0.25 = 609935.1245326500. A published row keeps no
    # previous balance; a reprocessed date replaces its row (OQ-21).
    written = CashDay(
        D,
        Decimal("0"),
        Decimal("-890064.6254673500"),
        Decimal("1500000.00"),
        Decimal("0.25"),
        Decimal("609935.1245326500"),
    )
    await publish.cash_day(written)
    async with session_factory() as session:
        first = await SqlPortfolioRepository(session).get_cash(D)

    await publish.cash(D, "100")
    async with session_factory() as session:
        second = await SqlPortfolioRepository(session).get_cash(D)

    assert first == replace(written, previous_cash_balance=None)
    assert first is not None and str(first.deposits) == "1500000.00"  # NUMERIC keeps the scale
    assert second is not None and second.cash_balance == Decimal("100")


async def test_the_aum_column_is_never_written(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # A2: AUM is computed on read; the kept ``aum`` column stays NULL (no migration).
    f28, _ = _ids(di1)
    await publish.cash(D, "100")
    await publish.positions(
        D,
        [(_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0"))],
        "1",
        _portfolio_pnl("0", "0"),
    )

    async with session_factory() as session:
        stored = await session.scalar(
            text("SELECT aum FROM portfolio.portfolio_metrics WHERE metric_date = :d"),
            {"d": D},
        )
    assert stored is None


async def test_rewriting_a_date_deletes_assets_no_longer_expected(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # OQ-10: rows exist exactly for the expected assets of the date.
    f28, f29 = _ids(di1)
    both = [
        (_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0")),
        (_position(f29, 5), _valued(f29, "1", ValuationStatus.COMPLETE), _pnl("0", "0")),
    ]
    await publish.positions(D, both, "2", _portfolio_pnl("0", "0"))
    await publish.positions(D, both[:1], "1", _portfolio_pnl("0", "0"))

    async with session_factory() as session:
        rows = await SqlPortfolioRepository(session).get_positions(D)
        day = await SqlPortfolioRepository(session).get_portfolio_day(D)

    assert [r.asset_id for r in rows] == [f28]
    assert day is not None and day.positions_market_value == Decimal("1")


async def test_a_flat_position_is_worth_zero_not_null(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    f28, _ = _ids(di1)
    await publish.positions(
        D,
        [
            (
                _position(f28, 0, None),
                _valued(f28, "0", ValuationStatus.NOT_REQUIRED),
                _pnl("0", "-12.5"),
            )
        ],
        "0",
        _portfolio_pnl("-12.5", "-12.5"),
    )

    async with session_factory() as session:
        (row,) = await SqlPortfolioRepository(session).get_positions(D)

    assert row.quantity == 0
    assert row.average_entry_pu is None
    assert row.financial_total == Decimal("0")
    assert row.valuation_status is ValuationStatus.NOT_REQUIRED


async def test_reads_never_mix_dates(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Exact date only (spec §5, §8.2): the neighbours' rows, cash included, are never read for D.
    f28, _ = _ids(di1)
    for offset, quantity in ((-1, 1), (0, 2), (1, 3)):
        on = D + timedelta(days=offset)
        await publish.positions(
            on,
            [
                (
                    _position(f28, quantity),
                    _valued(f28, str(quantity), ValuationStatus.COMPLETE),
                    _pnl("0", "0"),
                )
            ],
            str(quantity),
            _portfolio_pnl(str(offset), None),
        )
    await publish.cash(D - timedelta(days=1), "100")
    await publish.cash(D + timedelta(days=1), "300")

    async with session_factory() as session:
        repository = SqlPortfolioRepository(session)
        (row,) = await repository.get_positions(D)
        days = await repository.get_portfolio_days(D, D + timedelta(days=1))
        cash = await repository.get_cash(D)

    assert row.quantity == 2
    assert [d.date for d in days] == [D, D + timedelta(days=1)]
    assert cash is None


async def test_a_day_with_no_expected_asset_is_published_and_read_back(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # OQ-22 item 5: every position closed earlier, so D+1 has no expected asset and is still
    # published: no position row, market value 0, P&L exactly 0, both statuses COMPLETE,
    # cumulative carried. AUM = cash on read is a service rule (tests/unit/portfolio).
    next_day = D + timedelta(days=1)
    await publish.positions(next_day, [], "0", _portfolio_pnl("0", "-8034.1345282660"))

    async with session_factory() as session:
        repository = SqlPortfolioRepository(session)
        positions = await repository.get_positions(next_day)
        day = await repository.get_portfolio_day(next_day)
        previous = await build_portfolio_reader(session).get_previous_positions(
            next_day + timedelta(days=1)
        )

    assert positions == []
    assert day is not None
    assert day.positions_market_value == Decimal("0")
    assert (day.position_pnl, day.trades_pnl, day.daily_pnl) == (Decimal("0"),) * 3
    assert day.cumulative_pnl == Decimal("-8034.1345282660")
    assert day.valuation_status is COMPLETE
    assert day.pnl_status is COMPLETE
    assert previous is not None
    assert previous.state.positions == ()
    assert previous.cumulative_pnl == Decimal("-8034.1345282660")


async def test_the_previous_day_reader_carries_open_positions_and_cash(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # A position closed on D (quantity 0) is not carried to D+1 (OQ-10).
    f28, f29 = _ids(di1)
    await publish.cash(D, "199650.3745326500")
    await publish.positions(
        D,
        [
            (_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0")),
            (
                _position(f29, 0, None),
                _valued(f29, "0", ValuationStatus.NOT_REQUIRED),
                _pnl("0", "0"),
            ),
        ],
        "1",
        _portfolio_pnl("1", "1"),
    )

    async with session_factory() as session:
        reader = build_portfolio_reader(session)
        previous = await reader.get_previous_positions(D + timedelta(days=1))
        cash = await reader.get_previous_cash(D + timedelta(days=1))
        nothing = await reader.get_previous_positions(D)

    assert previous is not None
    assert previous.state.as_of == D
    assert previous.state.positions == (
        OpenPosition(f28, 10, Decimal("89006.4625467350"), Decimal("0.100000000000")),
    )
    assert cash is not None and cash.balance == Decimal("199650.3745326500")
    assert nothing is None


async def test_the_writer_never_commits(
    di1: Di1Catalogue, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # OQ-23: Processing commits the date; leaving its Unit of Work without a commit discards it.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await build_results_writer(uow.session).write_cash_day(
            CashDay(D, Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")),
        )

    async with session_factory() as session:
        assert await SqlPortfolioRepository(session).get_cash(D) is None


def _service(uow: SqlAlchemyUnitOfWork) -> PortfolioService:
    return build_portfolio_service(
        uow,
        assets=build_asset_reader(uow.session),
        prices=FakePriceReader(),
        date_statuses=FakeDateStatusReader(),
        clock=FakeClock(D),
    )


async def test_a_read_keeps_one_snapshot_while_a_date_is_published(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Spec §13 item 12 / portfolio.public: figures and statuses come from one snapshot. A read that
    # began before Processing commits D must not see D's rows half-way through (REPEATABLE READ).
    # Both reads run on one Unit of Work, so the snapshot is started once, before any query:
    # PostgreSQL refuses SET TRANSACTION after the transaction's first query.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        queries = _service(uow)
        before = await queries.get_summary(D)

        await publish.cash(D, "500")  # another transaction commits D

        during = await queries.get_summary(D)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        after = await _service(uow).get_summary(D)

    assert before.cash.balance is None
    assert during.cash.balance is None  # same snapshot as the first read
    assert after.cash.balance == Decimal("500")
