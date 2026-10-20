"""`PortfolioRepository` over the ``portfolio`` schema: rows in, records out, no business rule."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.pnl.public import CalculationCompleteness
from di1.modules.portfolio.application.services.repository import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.portfolio.domain.valuation import ValuationStatus
from di1.modules.portfolio.infrastructure.persistence.models import (
    CashBalanceRow,
    PortfolioMetricsRow,
    PositionMetricsRow,
    PositionRow,
)
from di1.modules.portfolio.infrastructure.persistence.queries import published


def _portfolio_day(row: PortfolioMetricsRow) -> PublishedPortfolioDay:
    return PublishedPortfolioDay(
        date=row.metric_date,
        positions_market_value=row.positions_market_value,
        position_pnl=row.position_pnl,
        trades_pnl=row.trades_pnl,
        daily_pnl=row.daily_pnl,
        cumulative_pnl=row.cumulative_pnl,
        valuation_status=CalculationCompleteness(row.valuation_status),
        pnl_status=CalculationCompleteness(row.pnl_status),
    )


def _position(position: PositionRow, metrics: PositionMetricsRow) -> PublishedPosition:
    return PublishedPosition(
        asset_id=position.asset_id,
        quantity=position.quantity,
        average_entry_pu=metrics.average_entry_pu,
        average_entry_rate=metrics.average_entry_rate,
        financial_total=metrics.financial_total,
        position_pnl=metrics.position_pnl,
        trades_pnl=metrics.trades_pnl,
        daily_pnl=metrics.daily_pnl,
        valuation_status=ValuationStatus(metrics.valuation_status),
        pnl_status=CalculationCompleteness(metrics.pnl_status),
    )


def _cash(row: CashBalanceRow) -> CashDay:
    return CashDay(
        date=row.balance_date,
        previous_cash_balance=None,
        cash_balance=row.cash_balance,
        trades_cash_flow=row.trades_cash_flow,
        deposits=row.deposits,
        withdrawals=row.withdrawals,
    )


class SqlPortfolioRepository:
    """Implements `PortfolioRepository` on the caller's session; it never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start_read_snapshot(self) -> None:
        await self._session.execute(published.READ_SNAPSHOT)

    async def replace_positions_day(
        self,
        day: PublishedPortfolioDay,
        positions: Sequence[PublishedPosition],
    ) -> None:
        await self._session.execute(published.delete_positions(day.date))
        if positions:
            await self._session.execute(
                published.insert_positions(
                    [
                        {"asset_id": p.asset_id, "position_date": day.date, "quantity": p.quantity}
                        for p in positions
                    ]
                )
            )
            await self._session.execute(
                published.insert_position_metrics(
                    [
                        {
                            "asset_id": p.asset_id,
                            "metric_date": day.date,
                            "average_entry_pu": p.average_entry_pu,
                            "average_entry_rate": p.average_entry_rate,
                            "financial_total": p.financial_total,
                            "position_pnl": p.position_pnl,
                            "trades_pnl": p.trades_pnl,
                            "daily_pnl": p.daily_pnl,
                            "valuation_status": p.valuation_status.value,
                            "pnl_status": p.pnl_status.value,
                        }
                        for p in positions
                    ]
                )
            )
        await self._session.execute(
            published.upsert_portfolio_metrics(
                {
                    "metric_date": day.date,
                    "positions_market_value": day.positions_market_value,
                    "position_pnl": day.position_pnl,
                    "trades_pnl": day.trades_pnl,
                    "daily_pnl": day.daily_pnl,
                    "cumulative_pnl": day.cumulative_pnl,
                    "valuation_status": day.valuation_status.value,
                    "pnl_status": day.pnl_status.value,
                }
            )
        )

    async def upsert_cash_day(self, cash: CashDay) -> None:
        await self._session.execute(
            published.upsert_cash_balance(
                {
                    "balance_date": cash.date,
                    "cash_balance": cash.cash_balance,
                    "trades_cash_flow": cash.trades_cash_flow,
                    "deposits": cash.deposits,
                    "withdrawals": cash.withdrawals,
                }
            )
        )

    async def get_cash(self, on: date) -> CashDay | None:
        row = await self._session.scalar(published.cash_balance(on))
        return None if row is None else _cash(row)

    async def get_portfolio_day(self, on: date) -> PublishedPortfolioDay | None:
        rows = await self._session.scalars(published.portfolio_metrics(on, on))
        found = rows.first()
        return None if found is None else _portfolio_day(found)

    async def get_portfolio_days(
        self, start_date: date, end_date: date
    ) -> Sequence[PublishedPortfolioDay]:
        rows = await self._session.scalars(published.portfolio_metrics(start_date, end_date))
        return [_portfolio_day(r) for r in rows]

    async def get_positions(self, on: date) -> Sequence[PublishedPosition]:
        result = await self._session.execute(published.positions_with_metrics(on))
        return [_position(p, m) for p, m in result]
