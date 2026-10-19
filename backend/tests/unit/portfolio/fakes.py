"""In-memory stand-ins for the unit tests of Portfolio's application services.

``InMemoryPortfolioRepository`` follows the contract of ``PortfolioRepository``; the integration
tests check the SQL implementation against the same rules. The readers of other modules are
faked through their public protocols only.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import InstrumentDescriptor
from di1.modules.portfolio.application.interfaces.repository import (
    PublishedCash,
    PublishedPortfolioDay,
    PublishedPosition,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.processing.public import DateStatus
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.input_kind import InputKind


class InMemoryPortfolioRepository:
    def __init__(self) -> None:
        self.days: dict[date, PublishedPortfolioDay] = {}
        self.positions: dict[date, tuple[PublishedPosition, ...]] = {}
        self.cash: dict[date, PublishedCash] = {}
        self.snapshots = 0

    async def start_read_snapshot(self) -> None:
        self.snapshots += 1

    async def replace_positions_day(
        self,
        day: PublishedPortfolioDay,
        positions: Sequence[PublishedPosition],
        *,
        cash_processed: bool,
    ) -> None:
        aum = self._aum(day.date, day.positions_market_value) if cash_processed else None
        self.days[day.date] = replace(day, aum=aum)
        self.positions[day.date] = tuple(sorted(positions, key=lambda p: p.asset_id))

    async def upsert_cash_day(self, cash: PublishedCash, *, positions_processed: bool) -> None:
        self.cash[cash.date] = cash
        day = self.days.get(cash.date)
        if day is not None:
            aum = self._aum(cash.date, day.positions_market_value) if positions_processed else None
            self.days[cash.date] = replace(day, aum=aum)

    async def get_cash(self, on: date) -> PublishedCash | None:
        return self.cash.get(on)

    async def get_portfolio_day(self, on: date) -> PublishedPortfolioDay | None:
        return self.days.get(on)

    async def get_portfolio_days(
        self, start_date: date, end_date: date
    ) -> Sequence[PublishedPortfolioDay]:
        return [self.days[d] for d in sorted(self.days) if start_date <= d <= end_date]

    async def get_positions(self, on: date) -> Sequence[PublishedPosition]:
        return self.positions.get(on, ())

    def _aum(self, on: date, market_value: Decimal | None) -> Decimal | None:
        cash = self.cash.get(on)
        if cash is None or market_value is None:
            return None
        return cash.cash_balance + market_value


class FakeUnitOfWork:
    """A Unit of Work the fakes ignore; the services only pass it through."""

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the unit tests use no session")

    async def commit(self) -> None:
        raise AssertionError("the services under test never commit")


class FakeDateStatusReader:
    def __init__(self, statuses: Mapping[date, DateStatus] | None = None) -> None:
        self.statuses = dict(statuses or {})
        self.seen_uows: list[UnitOfWork] = []

    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        self.seen_uows.append(uow)
        return {d: s for d, s in self.statuses.items() if start_date <= d <= end_date}


class FakePriceReader:
    def __init__(self) -> None:
        self.prices: dict[tuple[UUID, date], ReferencePriceRecord] = {}

    def add(self, asset_id: UUID, on: date, source: PriceSource, pu: str, rate: str | None) -> None:
        stamp = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
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

    async def get_preferred(
        self, asset_id: UUID, reference_date: date
    ) -> ReferencePriceRecord | None:
        return self.prices.get((asset_id, reference_date))

    async def get_preferred_many(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        return {k: v for k, v in self.prices.items() if k[0] in asset_ids and k[1] in dates}


class FakeAssetReader:
    def __init__(self, *instruments: tuple[UUID, str, date | None]) -> None:
        self.instruments = {
            asset_id: InstrumentDescriptor(
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
            )
            for asset_id, code, maturity in instruments
        }

    async def get_instrument(self, instrument_id: UUID) -> InstrumentDescriptor:
        return self.instruments[instrument_id]

    async def get_instruments(
        self, instrument_ids: Collection[UUID]
    ) -> Mapping[UUID, InstrumentDescriptor]:
        return {i: d for i, d in self.instruments.items() if i in instrument_ids}
