"""`PortfolioResultsWriter`: one date of the positions chain, mapped onto the published rows (OQ-10,
OQ-21, OQ-23, OQ-28, OQ-30). The cash day goes to its row unchanged; its SQL round trip is in
tests/integration/portfolio/test_published_rows.py."""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal
from uuid import UUID

import pytest

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.application.services.results_writer import DefaultResultsWriter
from di1.modules.portfolio.domain.positions import PositionDay, PositionsDay
from di1.modules.portfolio.domain.trade import Trade
from di1.modules.portfolio.domain.valuation import (
    AssetValuation,
    PortfolioValuation,
    ValuationStatus,
)
from tests.support.builders import DAY, DI1F27, DI1F28
from tests.unit.portfolio.fakes import InMemoryPortfolioRepository

COMPLETE = CalculationCompleteness.COMPLETE
MISSING = CalculationCompleteness.MISSING


def _buy(asset_id: UUID = DI1F27.id) -> Trade:
    return Trade(asset_id, DAY, time(10), 1, 10, Decimal("95000"), Decimal("0.105"))


def _positions(*asset_ids: UUID) -> PositionsDay:
    return PositionsDay(
        date=DAY,
        positions=tuple(
            PositionDay(a, 0, 10, Decimal("95000"), Decimal("0.105"), (_buy(a),)) for a in asset_ids
        ),
    )


def _valuation(*asset_ids: UUID, market_value: str | None = "951000") -> PortfolioValuation:
    return PortfolioValuation(
        date=DAY,
        assets=tuple(
            AssetValuation(a, Decimal("95100"), Decimal("951000"), ValuationStatus.COMPLETE)
            for a in asset_ids
        ),
        positions_market_value=None if market_value is None else Decimal(market_value),
        status=ValuationStatus.COMPLETE if market_value is not None else ValuationStatus.MISSING,
    )


def _asset_pnl(*asset_ids: UUID) -> dict[UUID, AssetPnLResult]:
    return {
        a: AssetPnLResult(Decimal("0"), Decimal("1000"), Decimal("1000"), COMPLETE, frozenset())
        for a in asset_ids
    }


PNL = PortfolioPnLResult(
    position_pnl=Decimal("0"),
    trades_pnl=Decimal("1000"),
    daily_pnl=Decimal("1000"),
    cumulative_pnl=Decimal("1500"),
    status=COMPLETE,
)
ZERO_PNL = PortfolioPnLResult(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("7"), COMPLETE)


def _empty_valuation(market_value: str | None) -> PortfolioValuation:
    return PortfolioValuation(
        DAY,
        (),
        None if market_value is None else Decimal(market_value),
        ValuationStatus.MISSING if market_value is None else ValuationStatus.COMPLETE,
    )


@pytest.mark.parametrize(
    ("market_value", "valuation_status"),
    [
        pytest.param("951000", COMPLETE, id="valued"),
        pytest.param(None, MISSING, id="market-value-missing"),
    ],
)
async def test_a_positions_day_maps_onto_the_published_rows(
    market_value: str | None, valuation_status: CalculationCompleteness
) -> None:
    repository = InMemoryPortfolioRepository()

    await DefaultResultsWriter(repository).write_positions_day(
        _positions(DI1F27.id),
        _valuation(DI1F27.id, market_value=market_value),
        _asset_pnl(DI1F27.id),
        PNL,
    )

    assert repository.positions[DAY] == (
        PublishedPosition(
            asset_id=DI1F27.id,
            quantity=10,
            average_entry_pu=Decimal("95000"),
            average_entry_rate=Decimal("0.105"),
            financial_total=Decimal("951000"),
            position_pnl=Decimal("0"),
            trades_pnl=Decimal("1000"),
            daily_pnl=Decimal("1000"),
            valuation_status=ValuationStatus.COMPLETE,
            pnl_status=COMPLETE,
        ),
    )
    assert repository.days[DAY] == PublishedPortfolioDay(
        date=DAY,
        positions_market_value=None if market_value is None else Decimal(market_value),
        position_pnl=Decimal("0"),
        trades_pnl=Decimal("1000"),
        daily_pnl=Decimal("1000"),
        cumulative_pnl=Decimal("1500"),
        valuation_status=valuation_status,
        pnl_status=COMPLETE,
    )


async def test_a_day_with_no_expected_asset_writes_only_the_portfolio_row() -> None:
    # OQ-22 item 5: every position closed earlier; market value 0, P&L 0, cumulative carried.
    repository = InMemoryPortfolioRepository()
    carried = replace(ZERO_PNL, cumulative_pnl=Decimal("1500"))

    await DefaultResultsWriter(repository).write_positions_day(
        PositionsDay(DAY, ()), _empty_valuation("0"), {}, carried
    )

    day = repository.days[DAY]
    assert repository.positions[DAY] == ()
    assert day.positions_market_value == Decimal("0")
    assert (day.position_pnl, day.trades_pnl, day.daily_pnl) == (Decimal("0"),) * 3
    assert day.valuation_status is COMPLETE
    assert day.pnl_status is COMPLETE
    assert day.cumulative_pnl == Decimal("1500")


@pytest.mark.parametrize(
    ("positions", "valuation", "asset_pnl", "pnl"),
    [
        # The three inputs must cover the same assets.
        pytest.param(
            _positions(DI1F27.id),
            _valuation(DI1F27.id, DI1F28.id),
            _asset_pnl(DI1F27.id),
            PNL,
            id="valued-asset-not-held",
        ),
        pytest.param(
            _positions(DI1F27.id, DI1F28.id),
            _valuation(DI1F27.id, DI1F28.id),
            _asset_pnl(DI1F27.id),
            PNL,
            id="held-asset-without-pnl",
        ),
        pytest.param(
            _positions(DI1F27.id),
            _valuation(DI1F27.id),
            _asset_pnl(DI1F27.id, DI1F28.id),
            PNL,
            id="pnl-for-an-asset-not-held",
        ),
        pytest.param(
            _positions(DI1F27.id),
            replace(_valuation(DI1F27.id), date=DAY.replace(day=5)),
            _asset_pnl(DI1F27.id),
            PNL,
            id="valuation-of-another-date",
        ),
        # Unavailable data is never stored as complete, nor a figure as missing (spec §8.3).
        pytest.param(
            _positions(DI1F27.id),
            replace(_valuation(DI1F27.id), positions_market_value=None),
            _asset_pnl(DI1F27.id),
            PNL,
            id="null-market-value-marked-complete",
        ),
        pytest.param(
            _positions(DI1F27.id),
            replace(
                _valuation(DI1F27.id),
                positions_market_value=Decimal("0"),
                status=ValuationStatus.MISSING,
            ),
            _asset_pnl(DI1F27.id),
            PNL,
            id="market-value-marked-missing",
        ),
        # OQ-22 item 5: with no expected asset the market value is 0 and position, trades and
        # daily P&L are exactly 0 (reviewer m4); anything else cannot come from an empty day.
        pytest.param(
            PositionsDay(DAY, ()), _empty_valuation("1"), {}, ZERO_PNL, id="empty-day-worth-1"
        ),
        pytest.param(
            PositionsDay(DAY, ()), _empty_valuation(None), {}, ZERO_PNL, id="empty-day-unvalued"
        ),
        pytest.param(
            PositionsDay(DAY, ()),
            _empty_valuation("0"),
            {},
            replace(ZERO_PNL, position_pnl=Decimal("1"), daily_pnl=Decimal("1")),
            id="empty-day-with-position-pnl",
        ),
        pytest.param(
            PositionsDay(DAY, ()),
            _empty_valuation("0"),
            {},
            replace(ZERO_PNL, trades_pnl=Decimal("-1"), daily_pnl=Decimal("-1")),
            id="empty-day-with-trades-pnl",
        ),
        pytest.param(
            PositionsDay(DAY, ()),
            _empty_valuation("0"),
            {},
            replace(ZERO_PNL, position_pnl=None, daily_pnl=None, status=MISSING),
            id="empty-day-with-missing-pnl",
        ),
    ],
)
async def test_inconsistent_inputs_are_rejected(
    positions: PositionsDay,
    valuation: PortfolioValuation,
    asset_pnl: dict[UUID, AssetPnLResult],
    pnl: PortfolioPnLResult,
) -> None:
    repository = InMemoryPortfolioRepository()

    with pytest.raises(ValueError):
        await DefaultResultsWriter(repository).write_positions_day(
            positions, valuation, asset_pnl, pnl
        )

    assert repository.days == {}  # nothing written
