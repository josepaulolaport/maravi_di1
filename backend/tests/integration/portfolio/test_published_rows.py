"""Portfolio's published rows against PostgreSQL 16: the writer, the previous-day reader and the
repository's reads (OQ-10, OQ-21, OQ-22, OQ-23, OQ-28, OQ-30).

Each write runs in its own Unit of Work and is committed by the test, as Processing commits a
date; the writer itself never commits."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.asset.dependencies import asset_reader
from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.dependencies import (
    portfolio_query_service,
    portfolio_reader,
    portfolio_repository,
    results_writer,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import OpenPosition, PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ReferenceSource,
    ValuationStatus,
)
from di1.modules.processing.public import ChainStatus, DateStatus
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork
from di1.shared.clock import FixedClock
from tests.integration.asset.conftest import Di1Catalogue
from tests.unit.portfolio.fakes import FakeDateStatusReader, FakePriceReader

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
        ReferenceSource.B3 if priced else None,
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
        cumulative_status=COMPLETE if cumulative is not None else MISSING,
        incomplete_assets=frozenset(),
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
        *,
        cash_processed: bool = True,
    ) -> None:
        valuation = PortfolioValuation(
            date=on,
            assets=tuple(v for _, v, _ in rows),
            positions_market_value=None if market_value is None else Decimal(market_value),
            aum=Decimal("-1"),  # must be ignored
            status=ValuationStatus.COMPLETE
            if market_value is not None
            else ValuationStatus.MISSING,
        )
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            await results_writer().write_positions_day(
                PositionsDay(on, tuple(p for p, _, _ in rows)),
                valuation,
                {p.asset_id: r for p, _, r in rows},
                pnl,
                uow=uow,
                other_chain_processed=cash_processed,
            )
            await uow.commit()

    async def cash(self, on: date, balance: str, *, positions_processed: bool = True) -> None:
        day = CashDay(
            on, Decimal("0"), Decimal("0"), Decimal(balance), Decimal("0"), Decimal(balance)
        )
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            await results_writer().write_cash_day(
                day, uow=uow, other_chain_processed=positions_processed
            )
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
        repository = portfolio_repository(session)
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
    assert day.aum is None
    assert day.valuation_status is MISSING


class TestAum:
    async def test_cash_then_positions(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        f28, _ = _ids(di1)
        await publish.cash(D, "609935.3745326500")
        await publish.positions(
            D,
            [
                (
                    _position(f28, 10),
                    _valued(f28, "890064.6254673500", ValuationStatus.COMPLETE),
                    _pnl("0", "0"),
                )
            ],
            "890064.6254673500",
            _portfolio_pnl("0", "0"),
        )

        assert await _aum(session_factory, D) == Decimal("1500000.0000000000")

    async def test_positions_then_cash_and_a_cash_correction(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        f28, _ = _ids(di1)
        await publish.positions(
            D,
            [
                (
                    _position(f28, 10),
                    _valued(f28, "890064.6254673500", ValuationStatus.COMPLETE),
                    _pnl("0", "0"),
                )
            ],
            "890064.6254673500",
            _portfolio_pnl("0", "0"),
        )
        assert await _aum(session_factory, D) is None  # no cash yet

        await publish.cash(D, "609935.3745326500")
        assert await _aum(session_factory, D) == Decimal("1500000.0000000000")

        await publish.cash(D, "100")  # reprocessed cash
        assert await _aum(session_factory, D) == Decimal("890164.6254673500")

    async def test_a_missing_market_value_leaves_aum_null(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        f28, _ = _ids(di1)
        await publish.cash(D, "100")
        await publish.positions(
            D,
            [(_position(f28, 10), _valued(f28, None, ValuationStatus.MISSING), _pnl(None, None))],
            None,
            _portfolio_pnl(None, None),
        )

        assert await _aum(session_factory, D) is None

    async def test_cash_of_another_date_is_never_used(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Exact date only (spec §5, §8.2): D−1's cash does not complete D's AUM.
        f28, _ = _ids(di1)
        await publish.cash(D - timedelta(days=1), "100")
        await publish.positions(
            D,
            [(_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0"))],
            "1",
            _portfolio_pnl("0", "0"),
        )

        assert await _aum(session_factory, D) is None


class TestAumNeedsTheOtherChainProcessed:
    """OQ-38: a chain's write nulls AUM when the other chain of the date is not processed."""

    async def test_positions_written_while_cash_is_not_processed(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        f28, _ = _ids(di1)
        await publish.cash(D, "100", positions_processed=False)
        await publish.positions(
            D,
            [(_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0"))],
            "1",
            _portfolio_pnl("0", "0"),
            cash_processed=False,
        )

        assert await _aum(session_factory, D) is None

    async def test_cash_written_while_positions_are_not_processed(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # A positions row kept from an earlier run does not complete AUM while its chain is FAILED.
        f28, _ = _ids(di1)
        await publish.positions(
            D,
            [(_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0"))],
            "1",
            _portfolio_pnl("0", "0"),
        )
        await publish.cash(D, "100", positions_processed=False)

        assert await _aum(session_factory, D) is None

    async def test_cash_written_while_positions_are_processed(
        self,
        di1: Di1Catalogue,
        publish: Publisher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        f28, _ = _ids(di1)
        await publish.positions(
            D,
            [(_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl("0", "0"))],
            "1",
            _portfolio_pnl("0", "0"),
            cash_processed=False,
        )
        await publish.cash(D, "100", positions_processed=True)

        assert await _aum(session_factory, D) == Decimal("101")


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
        rows = await portfolio_repository(session).get_positions(D)
        day = await portfolio_repository(session).get_portfolio_day(D)

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
        (row,) = await portfolio_repository(session).get_positions(D)

    assert row.quantity == 0
    assert row.average_entry_pu is None
    assert row.financial_total == Decimal("0")
    assert row.valuation_status is ValuationStatus.NOT_REQUIRED


async def test_reads_never_mix_dates(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
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

    async with session_factory() as session:
        repository = portfolio_repository(session)
        (row,) = await repository.get_positions(D)
        days = await repository.get_portfolio_days(D, D + timedelta(days=1))

    assert row.quantity == 2
    assert [d.date for d in days] == [D, D + timedelta(days=1)]


async def test_a_day_with_no_expected_asset_is_published_and_read_back(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # OQ-22 item 5: market value 0, AUM = cash, P&L 0, cumulative carried; no position row.
    await publish.cash(D, "500")
    await publish.positions(D, [], "0", _portfolio_pnl("0", "-8034.1345282660"))

    async with session_factory() as session:
        previous = await portfolio_reader(session).get_previous_positions(D + timedelta(days=1))
        assert await portfolio_repository(session).get_positions(D) == []

    assert previous is not None
    assert previous.state.positions == ()
    assert previous.cumulative_pnl == Decimal("-8034.1345282660")
    assert await _aum(session_factory, D) == Decimal("500")


async def test_the_previous_day_reader_carries_open_positions_and_cash(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
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
        reader = portfolio_reader(session)
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
        await results_writer().write_cash_day(
            CashDay(D, Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")),
            uow=uow,
            other_chain_processed=True,
        )

    async with session_factory() as session:
        assert await portfolio_repository(session).get_cash(D) is None


async def _aum(session_factory: async_sessionmaker[AsyncSession], on: date) -> Decimal | None:
    async with session_factory() as session:
        day = await portfolio_repository(session).get_portfolio_day(on)
    assert day is not None
    return day.aum


async def test_a_read_keeps_one_snapshot_while_a_date_is_published(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Spec §13 item 12 / portfolio.public: figures and statuses come from one snapshot. A read that
    # began before Processing commits D must not see D's rows half-way through (REPEATABLE READ).
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        queries = portfolio_query_service(
            uow,
            assets=asset_reader(uow.session),
            prices=FakePriceReader(),
            date_statuses=FakeDateStatusReader(),
            clock=FixedClock(D),
        )
        before = await queries.get_summary(D)

        await publish.cash(D, "500")  # another transaction commits D

        during = await queries.get_summary(D)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        after = await portfolio_query_service(
            uow,
            assets=asset_reader(uow.session),
            prices=FakePriceReader(),
            date_statuses=FakeDateStatusReader(),
            clock=FixedClock(D),
        ).get_summary(D)

    assert before.cash.balance is None
    assert during.cash.balance is None  # same snapshot as the first read
    assert after.cash.balance == Decimal("500")


async def test_a_position_closed_on_d_leaves_d_plus_one_with_no_asset(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # OQ-22 item 5 / spec §13: closed on D (row with quantity 0), D+1 has no expected asset and is
    # still published: market value 0, AUM = cash, P&L exactly 0, both statuses COMPLETE,
    # cumulative carried.
    f28, _ = _ids(di1)
    await publish.positions(
        D,
        [
            (
                _position(f28, 0, None),
                _valued(f28, "0", ValuationStatus.NOT_REQUIRED),
                _pnl("5", "-2"),
            )
        ],
        "0",
        _portfolio_pnl("3", "3"),
    )
    async with session_factory() as session:
        start = await portfolio_reader(session).get_previous_positions(D + timedelta(days=1))
    assert start is not None and start.state.positions == ()

    next_day = D + timedelta(days=1)
    await publish.cash(next_day, "250")
    await publish.positions(next_day, [], "0", _portfolio_pnl("0", "3"))

    async with session_factory() as session:
        repository = portfolio_repository(session)
        day = await repository.get_portfolio_day(next_day)
        assert await repository.get_positions(next_day) == []
    assert day is not None
    assert day.positions_market_value == Decimal("0")
    assert day.aum == Decimal("250")
    assert (day.position_pnl, day.trades_pnl, day.daily_pnl) == (Decimal("0"),) * 3
    assert day.cumulative_pnl == Decimal("3")
    assert day.valuation_status is COMPLETE
    assert day.pnl_status is COMPLETE


async def test_case_27_the_range_sum_skips_unprocessed_and_failed_days(
    di1: Di1Catalogue, publish: Publisher, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Spec §13 case 27, OQ-41 item 4: D1 100, D2 not processed, D3 −40, D4 FAILED over an older
    # published row (daily 999) → 100, 100, 60, 60; D4 shows FAILED with no daily P&L.
    f28, _ = _ids(di1)
    days = [D + timedelta(days=n) for n in range(4)]
    for on, daily in ((days[0], "100"), (days[2], "-40"), (days[3], "999")):
        held = (_position(f28, 10), _valued(f28, "1", ValuationStatus.COMPLETE), _pnl(daily, "0"))
        await publish.positions(on, [held], "1", _portfolio_pnl(daily, None))
    processed_at = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    statuses = FakeDateStatusReader(
        {
            on: DateStatus(on, status, None, processed_at, None)
            for on, status in (
                (days[0], ChainStatus.PROCESSED),
                (days[2], ChainStatus.PROCESSED_WITH_ISSUES),
                (days[3], ChainStatus.FAILED),
            )
        }
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        points = await portfolio_query_service(
            uow,
            assets=asset_reader(uow.session),
            prices=FakePriceReader(),
            date_statuses=statuses,
            clock=FixedClock(days[3]),
        ).get_pnl_series(days[0], days[3])

    assert [p.range_cumulative_pnl for p in points] == [
        Decimal("100"),
        Decimal("100"),
        Decimal("60"),
        Decimal("60"),
    ]
    assert [p.status for p in points] == [
        ChainStatus.PROCESSED,
        None,
        ChainStatus.PROCESSED_WITH_ISSUES,
        ChainStatus.FAILED,
    ]
    assert points[3].daily_pnl is None
