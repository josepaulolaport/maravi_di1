"""In-memory stand-ins for the unit tests of Portfolio's application services.

``InMemoryPortfolioRepository`` follows the contract of ``PortfolioRepository``; the integration
tests check the SQL implementation against the same rules. The readers of other modules are
faked through their public protocols only.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from di1.modules.asset.public import Instrument
from di1.modules.portfolio.application.ports import (
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.portfolio.domain.cash import CashDay
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.processing.public import DateStatus
from di1.shared.input_kind import InputKind
from tests.fakes.asset import CREATED_AT

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


class FakeDateStatusReader:
    def __init__(self, statuses: Mapping[date, DateStatus] | None = None) -> None:
        self.statuses = dict(statuses or {})

    async def get_date_statuses(
        self, start_date: date, end_date: date
    ) -> Mapping[date, DateStatus]:
        return {d: s for d, s in self.statuses.items() if start_date <= d <= end_date}


class FakePriceReader:
    def __init__(self) -> None:
        self.prices: dict[tuple[UUID, date], ReferencePriceRecord] = {}

    def add(
        self,
        asset_id: UUID,
        on: date,
        source: PriceSource,
        pu: str,
        rate: str | None,
        *,
        created_at: datetime | None = None,
    ) -> None:
        stamp = created_at or datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
        self.prices[(asset_id, on)] = ReferencePriceRecord(
            id=UUID(int=len(self.prices) + 1),
            asset_id=asset_id,
            reference_date=on,
            source=source,
            input_kind=InputKind.PU,
            pu=Decimal(pu),
            rate=None if rate is None else Decimal(rate),
            created_at=stamp,
            updated_at=stamp,
        )

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        return {k: v for k, v in self.prices.items() if k[0] in asset_ids and k[1] in dates}

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        # Part of the PriceReader protocol; Portfolio reads exact-date prices only (OQ-30).
        raise AssertionError("Portfolio never reads the latest price")


class FakeAssetReader:
    def __init__(self, *instruments: tuple[UUID, str, date | None]) -> None:
        self.instruments = {
            asset_id: Instrument(
                id=asset_id,
                code=code,
                product_id=UUID(int=0),
                product_code="DI1",
                instrument_type="FUTURE",
                asset_class="INTEREST_RATE_FUTURE",
                maturity_date=maturity,
                face_value=Decimal("100000"),
                multiplier=Decimal("1"),
                settlement_method="CASH",
                created_at=CREATED_AT,
            )
            for asset_id, code, maturity in instruments
        }

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: d for i, d in self.instruments.items() if i in instrument_ids}
