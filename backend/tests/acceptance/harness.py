"""Phase 1 acceptance harness: the worker's own daily steps on in-memory facts, without a database.

Each calendar day of the range runs what Processing's worker runs for one date (spec §7, §8;
interfaces.md "Processing" step 2): ``process_positions_day`` and ``process_cash_day`` from
``run_chains``, the very functions the run processor calls, from the zero state (spec §7.1, OQ-4).
They read Ledger, Prices and Asset through the in-memory readers of the processing unit tests
(``tests/unit/processing/run_fakes.py``) and the published D−1 from this harness's own writer, so
the exact-date price rule (spec §5), the reference PU of 0 after maturity (spec §7.4, OQ-1) and the
per-asset P&L then aggregation (spec §8) are production's, not a copy.

The writer stands in for Portfolio's ``PortfolioResultsWriter`` and repository: it keeps each date's
published chains and recomputes the date's AUM the way the repository's SQL does (cash + market
value, null when either side is or when the other chain is not processed; OQ-21, OQ-38). The SQL
itself is proven in phase 2.

Choosing MANUAL over B3 is Prices' job and is covered in phase 2 (over HTTP): here a scenario
gives the already preferred PU of each (asset, date). Expected values never come from this file:
every test computes them by hand from the spec formulas.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

from di1.modules.pnl.public import AssetPnLResult, PortfolioPnLResult
from di1.modules.portfolio.public import (
    AssetValuation,
    CashBalance,
    CashDay,
    PortfolioValuation,
    PositionDay,
    PositionsDay,
    PreviousPositionsDay,
    Trade,
)
from di1.modules.processing.application.ports import ChainPorts
from di1.modules.processing.application.services.run_chains import (
    process_cash_day,
    process_positions_day,
)
from di1.modules.processing.domain.issues import IssueRecord
from di1.shared.decimals import financial_context
from tests.support.builders import di1_contract, ledger_cash, ledger_trade
from tests.support.fakes import FakeAssetReader, FakeLedger, FakePriceReader

ONE_DAY = timedelta(days=1)
ZERO = Decimal("0")

DI1F28 = UUID("00000000-0000-0000-0000-00000000f028")
DI1F29 = UUID("00000000-0000-0000-0000-00000000f029")
DI1F27 = UUID("00000000-0000-0000-0000-00000000f027")

MATURITIES: dict[UUID, date] = {
    DI1F27: date(2027, 1, 6),  # a short-dated contract for the maturity cases (OQ-1)
    DI1F28: date(2028, 1, 1),  # the challenge's contract
    DI1F29: date(2029, 1, 1),
}


def trade(
    asset_id: UUID,
    on: date,
    quantity: int,
    pu: str,
    rate: str = "0.1",
    *,
    at: str = "10:00",
    seq: int = 1,
) -> Trade:
    """A Ledger trade as Portfolio reads it: buys positive, sells negative, execution PU/rate."""
    return Trade(
        asset_id=asset_id,
        trade_date=on,
        trade_time=time.fromisoformat(at),
        seq=seq,
        signed_quantity=quantity,
        execution_pu=Decimal(pu),
        execution_rate=Decimal(rate),
    )


@dataclass(frozen=True)
class Facts:
    """What Ledger and Prices hold for a scenario.

    ``deposits`` and ``withdrawals`` are daily totals, positive amounts. ``prices`` is the
    preferred exact-date reference PU per (asset, date)."""

    trades: Sequence[Trade] = ()
    deposits: Mapping[date, Decimal] = field(default_factory=dict)
    withdrawals: Mapping[date, Decimal] = field(default_factory=dict)
    prices: Mapping[tuple[UUID, date], Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionsResult:
    """The positions chain as published for one date, with the date's Pendências and AUM."""

    positions_day: PositionsDay
    valuation: PortfolioValuation
    asset_pnl: Mapping[UUID, AssetPnLResult]
    pnl: PortfolioPnLResult
    issues: Sequence[IssueRecord]
    aum: Decimal | None

    @property
    def expected_assets(self) -> set[UUID]:
        return {p.asset_id for p in self.positions_day.positions}

    def position(self, asset_id: UUID) -> PositionDay:
        return next(p for p in self.positions_day.positions if p.asset_id == asset_id)

    def valued(self, asset_id: UUID) -> AssetValuation:
        return next(v for v in self.valuation.assets if v.asset_id == asset_id)


@dataclass(frozen=True)
class DayResult(PositionsResult):
    """Both chains of one date of an ALL run."""

    cash: CashDay


def run(facts: Facts, first_day: date, last_day: date) -> dict[date, DayResult]:
    """Every calendar day of [first_day, last_day] as one ALL run from the zero state: positions,
    then cash, in the date's transaction (interfaces.md "Processing", OQ-21)."""
    published = _publish(facts, first_day, last_day, positions=True, cash=True)
    return {
        day: DayResult(**vars(published.positions_result(day)), cash=published.cash[day])
        for day in _days(first_day, last_day)
    }


def run_positions(facts: Facts, first_day: date, last_day: date) -> dict[date, PositionsResult]:
    """A POSITIONS run: the cash chain is never processed, so AUM stays null (OQ-21, OQ-38)."""
    published = _publish(facts, first_day, last_day, positions=True, cash=False)
    return {day: published.positions_result(day) for day in _days(first_day, last_day)}


def run_cash(facts: Facts, first_day: date, last_day: date) -> dict[date, CashDay]:
    """A CASH run: no position, valuation or price is computed (OQ-21)."""
    published = _publish(facts, first_day, last_day, positions=False, cash=True)
    return {day: published.cash[day] for day in _days(first_day, last_day)}


@dataclass(frozen=True)
class _PositionsWrite:
    day: PositionsDay
    valuation: PortfolioValuation
    asset_pnl: Mapping[UUID, AssetPnLResult]
    pnl: PortfolioPnLResult


@dataclass
class _Published:
    """``PortfolioResultsWriter`` and ``PortfolioReader`` (portfolio/public.py) in memory."""

    positions: dict[date, _PositionsWrite] = field(default_factory=dict)
    cash: dict[date, CashDay] = field(default_factory=dict)
    issues: dict[date, list[IssueRecord]] = field(default_factory=dict)

    async def write_positions_day(
        self,
        day: PositionsDay,
        valuation: PortfolioValuation,
        asset_pnl: Mapping[UUID, AssetPnLResult],
        pnl: PortfolioPnLResult,
    ) -> None:
        self.positions[day.date] = _PositionsWrite(day, valuation, asset_pnl, pnl)

    async def write_cash_day(self, day: CashDay) -> None:
        self.cash[day.date] = day

    async def get_previous_positions(self, before_date: date) -> PreviousPositionsDay | None:
        written = self.positions.get(before_date - ONE_DAY)
        if written is None:
            return None
        return PreviousPositionsDay(
            state=written.day.closing_state(), cumulative_pnl=written.pnl.cumulative_pnl
        )

    async def get_previous_cash(self, before_date: date) -> CashBalance | None:
        written = self.cash.get(before_date - ONE_DAY)
        return None if written is None else written.closing_balance()

    def positions_result(self, day: date) -> PositionsResult:
        written = self.positions[day]
        return PositionsResult(
            positions_day=written.day,
            valuation=written.valuation,
            asset_pnl=written.asset_pnl,
            pnl=written.pnl,
            issues=tuple(self.issues[day]),
            aum=self._aum(day),
        )

    def _aum(self, on: date) -> Decimal | None:
        """As the Carteira reads it (OQ-21, OQ-38): the date's cash plus its market value, null
        when either chain is not published on the date or the market value is missing."""
        cash = self.cash.get(on)
        market_value = self.positions[on].valuation.positions_market_value
        if cash is None or market_value is None:
            return None
        with financial_context():
            return cash.cash_balance + market_value


def _publish(
    facts: Facts, first_day: date, last_day: date, *, positions: bool, cash: bool
) -> _Published:
    """Runs the chains' production steps day by day; the first day starts from the zero state,
    so no fact may be dated before it (OQ-26, OQ-40 item 5)."""
    dated = [t.trade_date for t in facts.trades] + [*facts.deposits, *facts.withdrawals]
    if any(on < first_day for on in dated):
        raise ValueError(f"a fact is dated before {first_day}, which starts from the zero state")
    published = _Published()
    ports = ChainPorts(
        ledger=_ledger(facts),
        prices=_prices(facts),
        assets=FakeAssetReader(*(di1_contract("DI1", i, m) for i, m in MATURITIES.items())),
        portfolio=published,
        writer=published,
    )

    async def every_day() -> None:
        for day in _days(first_day, last_day):
            zero_state = day == first_day
            if positions:
                published.issues[day] = await process_positions_day(
                    day,
                    zero_state=zero_state,
                    ports=ports,
                )
            if cash:
                await process_cash_day(
                    day,
                    zero_state=zero_state,
                    ports=ports,
                )

    asyncio.run(every_day())
    return published


def _ledger(facts: Facts) -> FakeLedger:
    ledger = FakeLedger(
        trades=[
            ledger_trade(
                t.asset_id,
                t.trade_date,
                t.signed_quantity,
                str(t.execution_pu),
                str(t.execution_rate),
                seq=t.seq,
                at=t.trade_time,
            )
            for t in facts.trades
        ]
    )
    for amounts, sign in ((facts.deposits, ""), (facts.withdrawals, "-")):
        for on, amount in amounts.items():
            ledger.movements.append(ledger_cash(on, f"{sign}{amount}", seq=len(ledger.movements)))
    return ledger


def _prices(facts: Facts) -> FakePriceReader:
    prices = FakePriceReader()
    for (asset_id, on), pu in facts.prices.items():
        prices.set(asset_id, on, str(pu))
    return prices


def _days(first_day: date, last_day: date) -> list[date]:
    return [first_day + timedelta(days=n) for n in range((last_day - first_day).days + 1)]
