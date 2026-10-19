"""`PortfolioResultsWriter` (portfolio/public.py): one date of a chain, written inside
Processing's date transaction, never committed here (OQ-23)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import UUID

from di1.modules.pnl.public import AssetPnLResult, CalculationCompleteness, PortfolioPnLResult
from di1.modules.portfolio.application.interfaces.repository import (
    PortfolioRepository,
    PublishedCash,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.positions import PositionsDay
from di1.modules.portfolio.domain.valuation import PortfolioValuation, ValuationStatus
from di1.platform.database.unit_of_work import UnitOfWork


class ResultsWriter:
    """Implements `di1.modules.portfolio.public.PortfolioResultsWriter`.

    ``repository_for`` builds the repository on the caller's Unit of Work, so the rows land in
    Processing's transaction for the date. ``other_chain_processed`` is Processing's answer
    for the other chain of the date (PROCESSED or PROCESSED_WITH_ISSUES); when ``False`` the
    written AUM is null (OQ-38).
    """

    def __init__(self, repository_for: Callable[[UnitOfWork], PortfolioRepository]) -> None:
        self._repository_for = repository_for

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
        if valuation.date != day.date:
            raise ValueError(f"the valuation is of {valuation.date}, the positions of {day.date}")
        if (valuation.status is ValuationStatus.MISSING) != (
            valuation.positions_market_value is None
        ):
            raise ValueError("a market value is missing exactly when its valuation is MISSING")
        if not day.positions and (
            valuation.positions_market_value != 0
            or any(v != 0 for v in (pnl.position_pnl, pnl.trades_pnl, pnl.daily_pnl))
        ):
            # OQ-22 item 5: a day with no expected asset is worth 0 and its P&L is exactly 0.
            raise ValueError(f"{day.date} has no expected asset but a market value or P&L")
        held = {p.asset_id for p in day.positions}
        valued = {v.asset_id: v for v in valuation.assets}
        if held != set(valued) or held != set(asset_pnl):
            raise ValueError(f"positions, valuation and P&L of {day.date} cover different assets")
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
            aum=None,  # recomputed by the repository from the date's published cash
            position_pnl=pnl.position_pnl,
            trades_pnl=pnl.trades_pnl,
            daily_pnl=pnl.daily_pnl,
            cumulative_pnl=pnl.cumulative_pnl,
            valuation_status=(
                CalculationCompleteness.MISSING
                if valuation.status is ValuationStatus.MISSING
                else CalculationCompleteness.COMPLETE
            ),
            pnl_status=pnl.status,
        )
        await self._repository_for(uow).replace_positions_day(
            portfolio_day, positions, cash_processed=other_chain_processed
        )

    async def write_cash_day(
        self, day: CashDay, *, uow: UnitOfWork, other_chain_processed: bool
    ) -> None:
        await self._repository_for(uow).upsert_cash_day(
            PublishedCash(
                date=day.date,
                cash_balance=day.cash_balance,
                trades_cash_flow=day.trades_cash_flow,
                deposits=day.deposits,
                withdrawals=day.withdrawals,
            ),
            positions_processed=other_chain_processed,
        )
