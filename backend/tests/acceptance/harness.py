"""Phase 1 acceptance harness: the pure engines composed day by day, without a database.

It runs the positions and cash chains (``portfolio.public``), values each day
(``ValuationCalculator``) and attributes P&L per asset, then aggregates (``pnl.public``), the way
spec §7 and §8 describe one processed day. It stands in for Prices and Processing in two facts
the spec states for the caller of the engines; they are stand-ins here, proven in phase 2:

- the reference PU of a day is the exact-date preferred price, never carried forward (spec §5);
- after maturity the reference PU is 0 by definition and no price is read (spec §7.4, OQ-1).

Choosing MANUAL over B3 is Prices' job and is covered in phase 2 (over HTTP): here a scenario
gives the already preferred PU of each (asset, date). Expected values never come from this file:
every test computes them by hand from the spec formulas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

from di1.modules.pnl.public import (
    AssetPnLCalculator,
    AssetPnLResult,
    PnLTrade,
    PortfolioPnLCalculator,
    PortfolioPnLResult,
)
from di1.modules.portfolio.public import (
    AccountingDay,
    AccountingState,
    AssetValuation,
    AssetValuationInput,
    PortfolioAccounting,
    PortfolioValuation,
    PositionDay,
    ReferenceSource,
    Trade,
    ValuationCalculator,
)

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
class DayResult:
    accounting: AccountingDay
    valuation: PortfolioValuation
    asset_pnl: Mapping[UUID, AssetPnLResult]
    pnl: PortfolioPnLResult

    @property
    def expected_assets(self) -> set[UUID]:
        return {p.asset_id for p in self.accounting.positions}

    def position(self, asset_id: UUID) -> PositionDay:
        return next(p for p in self.accounting.positions if p.asset_id == asset_id)

    def valued(self, asset_id: UUID) -> AssetValuation:
        return next(v for v in self.valuation.assets if v.asset_id == asset_id)


def reference_pu(facts: Facts, asset_id: UUID, on: date) -> Decimal | None:
    """The reference PU the P&L reads for ``on``: 0 after maturity (OQ-1), otherwise the exact
    date's price or ``None`` (no carry-forward, spec §5)."""
    if on > MATURITIES[asset_id]:
        return ZERO
    return facts.prices.get((asset_id, on))


def run(facts: Facts, first_day: date, last_day: date) -> dict[date, DayResult]:
    """Every calendar day of [first_day, last_day] from the zero state (spec §7.1, OQ-4)."""
    accounting = PortfolioAccounting()
    valuation = ValuationCalculator()
    asset_calculator = AssetPnLCalculator()
    portfolio_calculator = PortfolioPnLCalculator()

    state = AccountingState.zero(first_day - ONE_DAY)
    cumulative: Decimal | None = ZERO
    results: dict[date, DayResult] = {}
    day = first_day
    while day <= last_day:
        accounting_day = accounting.calculate_day(
            state,
            [t for t in facts.trades if t.trade_date == day],
            facts.deposits.get(day, ZERO),
            facts.withdrawals.get(day, ZERO),
            day,
        )
        day_valuation = valuation.calculate_day(
            day,
            [_valuation_input(facts, p, day) for p in accounting_day.positions],
            accounting_day.cash_balance,
        )
        asset_pnl = {
            p.asset_id: asset_calculator.calculate(
                p.previous_quantity,
                [PnLTrade(t.signed_quantity, t.execution_pu) for t in p.trades],
                reference_pu(facts, p.asset_id, day - ONE_DAY),
                reference_pu(facts, p.asset_id, day),
            )
            for p in accounting_day.positions
        }
        day_pnl = portfolio_calculator.aggregate(
            {p.asset_id for p in accounting_day.positions}, asset_pnl, cumulative
        )
        results[day] = DayResult(accounting_day, day_valuation, asset_pnl, day_pnl)
        cumulative = day_pnl.cumulative_pnl
        state = accounting_day.closing_state()
        day += ONE_DAY
    return results


def _valuation_input(facts: Facts, position: PositionDay, on: date) -> AssetValuationInput:
    maturity = MATURITIES[position.asset_id]
    # Past maturity no price is read: the calculator sets the PU to 0 (OQ-1).
    pu = None if on > maturity else facts.prices.get((position.asset_id, on))
    return AssetValuationInput(
        asset_id=position.asset_id,
        quantity=position.quantity,
        maturity_date=maturity,
        reference_pu=pu,
        reference_source=None if pu is None else ReferenceSource.MANUAL,
    )
