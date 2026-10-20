"""In-memory collaborators of the worker's chain steps: Ledger, Prices, Asset and Portfolio as
their ``public.py`` describes them, and a writer that records what it was given."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from di1.modules.asset.public import Instrument
from di1.modules.ledger.public import EntryType, LedgerEntry
from di1.modules.pnl.public import AssetPnLResult, PortfolioPnLResult
from di1.modules.portfolio.public import (
    CashBalance,
    CashDay,
    PortfolioResultsWriter,
    PortfolioValuation,
    PositionsDay,
    PreviousPositionsDay,
)
from di1.modules.prices.public import PriceSource, ReferencePriceRecord
from di1.modules.processing.application.ports import ChainPorts
from di1.shared.input_kind import InputKind
from tests.support.builders import CREATED_AT

CREATED = datetime(2026, 10, 1, tzinfo=UTC)


def trade(
    asset_id: UUID,
    day: date,
    quantity: int,
    pu: str,
    rate: str = "0.1",
    *,
    seq: int = 1,
    at: time = time(10),
) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.TRADE,
        entry_date=day,
        entry_time=at,
        seq=seq,
        created_at=CREATED,
        asset_id=asset_id,
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal(rate),
        input_kind=InputKind.PU,
        cash_amount=None,
    )


def cash_movement(day: date, amount: str, *, seq: int = 1) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.CASH,
        entry_date=day,
        entry_time=time(9),
        seq=seq,
        created_at=CREATED,
        asset_id=None,
        signed_quantity=None,
        execution_pu=None,
        execution_rate=None,
        input_kind=None,
        cash_amount=Decimal(amount),
    )


@dataclass
class FakeLedger:
    trades: list[LedgerEntry] = field(default_factory=list)
    movements: list[LedgerEntry] = field(default_factory=list)
    asked: list[tuple[date, EntryType | None]] = field(default_factory=list)

    async def get_trades(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        found = [t for t in self.trades if start_date <= t.entry_date <= end_date]
        return sorted(found, key=lambda t: t.order_key)

    async def get_cash_movements(self, start_date: date, end_date: date) -> Sequence[LedgerEntry]:
        found = [m for m in self.movements if start_date <= m.entry_date <= end_date]
        return sorted(found, key=lambda m: m.order_key)

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        self.asked.append((day, entry_type))
        trades = any(t.entry_date <= day for t in self.trades)
        if entry_type is EntryType.TRADE:
            return trades
        return trades or any(m.entry_date <= day for m in self.movements)


@dataclass
class FakePrices:
    pus: dict[tuple[UUID, date], tuple[str, PriceSource]] = field(default_factory=dict)

    def set(
        self, asset_id: UUID, day: date, pu: str, source: PriceSource = PriceSource.MANUAL
    ) -> None:
        self.pus[(asset_id, day)] = (pu, source)

    async def get(
        self, asset_ids: Collection[UUID], dates: Collection[date]
    ) -> Mapping[tuple[UUID, date], ReferencePriceRecord]:
        found: dict[tuple[UUID, date], ReferencePriceRecord] = {}
        for key, (pu, source) in self.pus.items():
            if key[0] in asset_ids and key[1] in dates:
                found[key] = ReferencePriceRecord(
                    id=uuid4(),
                    asset_id=key[0],
                    reference_date=key[1],
                    source=source,
                    input_kind=InputKind.PU,
                    pu=Decimal(pu),
                    rate=None,
                    created_at=CREATED,
                    updated_at=CREATED,
                )
        return found

    async def latest(self, asset_ids: Collection[UUID]) -> Mapping[UUID, ReferencePriceRecord]:
        latest: dict[UUID, ReferencePriceRecord] = {}
        for key, (pu, source) in self.pus.items():
            if key[0] not in asset_ids:
                continue
            record = ReferencePriceRecord(
                id=uuid4(),
                asset_id=key[0],
                reference_date=key[1],
                source=source,
                input_kind=InputKind.PU,
                pu=Decimal(pu),
                rate=None,
                created_at=CREATED,
                updated_at=CREATED,
            )
            current = latest.get(key[0])
            if current is None or record.reference_date > current.reference_date:
                latest[key[0]] = record
        return latest


@dataclass
class FakeInstruments:
    maturities: dict[UUID, date] = field(default_factory=dict)

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self._descriptor(i) for i in instrument_ids if i in self.maturities}

    def _descriptor(self, instrument_id: UUID) -> Instrument:
        return Instrument(
            id=instrument_id,
            code=f"DI1-{instrument_id.int % 1000}",
            product_id=UUID(int=1),
            product_code="DI1",
            instrument_type="FUTURE",
            asset_class="INTEREST_RATE_FUTURE",
            maturity_date=self.maturities[instrument_id],
            face_value=Decimal("100000"),
            multiplier=Decimal("1"),
            settlement_method="CASH",
            created_at=CREATED_AT,
        )


@dataclass
class FakePortfolio:
    """The published D−1 of each chain, keyed by D−1."""

    positions: dict[date, PreviousPositionsDay] = field(default_factory=dict)
    cash: dict[date, CashBalance] = field(default_factory=dict)

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        return self.positions.get(before_date.fromordinal(before_date.toordinal() - 1))

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        return self.cash.get(before_date.fromordinal(before_date.toordinal() - 1))


@dataclass(frozen=True)
class PositionsWrite:
    day: PositionsDay
    valuation: PortfolioValuation
    asset_pnl: Mapping[UUID, AssetPnLResult]
    pnl: PortfolioPnLResult


@dataclass(frozen=True)
class CashWrite:
    day: CashDay


@dataclass
class RecordingWriter:
    positions: list[PositionsWrite] = field(default_factory=list)
    cash: list[CashWrite] = field(default_factory=list)

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        self.positions.append(PositionsWrite(day, valuation, asset_pnl, pnl))

    async def write_cash_day(self, day: CashDay) -> None:
        self.cash.append(CashWrite(day))


@dataclass
class World:
    """Everything the chain steps read."""

    ledger: FakeLedger = field(default_factory=FakeLedger)
    prices: FakePrices = field(default_factory=FakePrices)
    instruments: FakeInstruments = field(default_factory=FakeInstruments)
    portfolio: FakePortfolio = field(default_factory=FakePortfolio)

    def ports(self, writer: PortfolioResultsWriter) -> ChainPorts:
        return ChainPorts(
            ledger=self.ledger,
            prices=self.prices,
            assets=self.instruments,
            portfolio=self.portfolio,
            writer=writer,
        )
