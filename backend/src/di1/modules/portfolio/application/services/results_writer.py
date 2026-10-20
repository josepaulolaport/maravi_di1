"""`PortfolioResultsWriter` (portfolio/public.py): one date of a chain, written inside
Processing's date transaction, never committed here (OQ-23)."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.ports import (
    PortfolioRepository,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import PositionsDay
from di1.modules.portfolio.domain.valuation import PortfolioValuation, ValuationStatus


class DefaultResultsWriter:
    """Public `PortfolioResultsWriter` on the repository of Processing's date transaction, so
    the rows land in it. AUM is not written: the read models compute it (OQ-21, OQ-38)."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        if valuation.date != day.date:
            raise PortfolioError(
                f"the valuation is of {valuation.date}, the positions of {day.date}"
            )
        if (valuation.status is ValuationStatus.MISSING) != (
            valuation.positions_market_value is None
        ):
            raise PortfolioError("a market value is missing exactly when its valuation is MISSING")
        if not day.positions and (
            valuation.positions_market_value != 0
            or any(v != 0 for v in (pnl.position_pnl, pnl.trades_pnl, pnl.daily_pnl))
        ):
            # OQ-22 item 5: a day with no expected asset is worth 0 and its P&L is exactly 0.
            raise PortfolioError(f"{day.date} has no expected asset but a market value or P&L")
        held = {p.asset_id for p in day.positions}
        valued = {v.asset_id: v for v in valuation.assets}
        if held != set(valued) or held != set(asset_pnl):
            raise PortfolioError(
                f"positions, valuation and P&L of {day.date} cover different assets"
            )
        positions = [
            PublishedPosition(
                asset_id=p.asset_id,
                quantity=p.quantity,
                average_entry_pu=p.average_entry_pu,
                average_entry_rate=p.average_entry_rate,
                financial_total=valued[p.asset_id].financial_total,
                position_pnl=asset_pnl[p.asset_id].position_pnl,
                trades_pnl=asset_pnl[p.asset_id].trades_pnl,
                daily_pnl=asset_pnl[p.asset_id].daily_pnl,
                valuation_status=valued[p.asset_id].status,
                pnl_status=asset_pnl[p.asset_id].status,
            )
            for p in day.positions
        ]
        portfolio_day = PublishedPortfolioDay(
            date=day.date,
            positions_market_value=valuation.positions_market_value,
            position_pnl=pnl.position_pnl,
            trades_pnl=pnl.trades_pnl,
            daily_pnl=pnl.daily_pnl,
            cumulative_pnl=pnl.cumulative_pnl,
            valuation_status=CalculationCompleteness(valuation.status),
            pnl_status=pnl.status,
        )
        await self._repository.replace_positions_day(portfolio_day, positions)

    async def write_cash_day(self, day: CashDay) -> None:
        await self._repository.upsert_cash_day(day)
