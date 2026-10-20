"""`PortfolioReader` (portfolio/public.py): the published D−1 each chain of D starts from
(OQ-21, OQ-22). Whether D−1 counts as processed is Processing's check on ``date_status``
(OQ-31); this reader only returns what was published."""

from __future__ import annotations

from datetime import date, timedelta

from di1.modules.portfolio.application.services.repository import PortfolioRepository
from di1.modules.portfolio.domain.cash import CashBalance
from di1.modules.portfolio.domain.errors import PortfolioError
from di1.modules.portfolio.domain.positions import OpenPosition, PositionState
from di1.modules.portfolio.public import PreviousPositionsDay

ONE_DAY = timedelta(days=1)


class PortfolioReader:
    """Public `PortfolioReader` on the caller's session."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        previous = before_date - ONE_DAY
        day = await self._repository.get_portfolio_day(previous)
        if day is None:
            return None
        carried = []
        for p in await self._repository.get_positions(previous):
            if p.quantity == 0:
                continue  # closed on D−1: not expected on D unless it trades (OQ-10)
            if p.average_entry_pu is None or p.average_entry_rate is None:
                raise PortfolioError(
                    f"published position {p.asset_id} on {previous} has no average"
                )
            carried.append(
                OpenPosition(p.asset_id, p.quantity, p.average_entry_pu, p.average_entry_rate)
            )
        return PreviousPositionsDay(
            state=PositionState(as_of=previous, positions=tuple(carried)),
            cumulative_pnl=day.cumulative_pnl,
        )

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        previous = before_date - ONE_DAY
        cash = await self._repository.get_cash(previous)
        return None if cash is None else CashBalance(as_of=previous, balance=cash.cash_balance)
