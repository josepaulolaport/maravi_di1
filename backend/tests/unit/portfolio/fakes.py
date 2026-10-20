"""In-memory stand-ins for the unit tests of Portfolio's application services.

``InMemoryPortfolioRepository`` follows the contract of ``PortfolioRepository``; the integration
tests check the SQL implementation against the same rules. The readers of other modules are
faked in ``tests.support.fakes``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay

ZERO = Decimal("0")


def stored_cash(
    on: date,
    balance: Decimal,
    trades: Decimal = ZERO,
    deposits: Decimal = ZERO,
    withdrawals: Decimal = ZERO,
) -> CashDay:
    """A published ``cash_balances`` row: no previous balance on the stored shape."""
    return CashDay(
        date=on,
        previous_cash_balance=None,
        trades_cash_flow=trades,
        deposits=deposits,
        withdrawals=withdrawals,
        cash_balance=balance,
    )


class InMemoryPortfolioRepository:
    def __init__(self) -> None:
        self.days: dict[date, PublishedPortfolioDay] = {}
        self.positions: dict[date, tuple[PublishedPosition, ...]] = {}
        self.cash: dict[date, CashDay] = {}

    async def start_read_snapshot(self) -> None:
        pass  # one snapshot per transaction: checked against PostgreSQL in the integration tests

    async def replace_positions_day(
        self,
        day: PublishedPortfolioDay,
        positions: Sequence[PublishedPosition],
    ) -> None:
        self.days[day.date] = day
        self.positions[day.date] = tuple(sorted(positions, key=lambda p: p.asset_id))

    async def upsert_cash_day(self, cash: CashDay) -> None:
        self.cash[cash.date] = cash

    async def get_cash(self, on: date) -> CashDay | None:
        return self.cash.get(on)

    async def get_portfolio_day(self, on: date) -> PublishedPortfolioDay | None:
        return self.days.get(on)

    async def get_portfolio_days(
        self, start_date: date, end_date: date
    ) -> Sequence[PublishedPortfolioDay]:
        return [self.days[d] for d in sorted(self.days) if start_date <= d <= end_date]

    async def get_positions(self, on: date) -> Sequence[PublishedPosition]:
        return self.positions.get(on, ())
