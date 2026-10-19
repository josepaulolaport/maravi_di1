"""One date of each chain: read the facts, run the pure calculators, write the published rows
(interfaces.md "Processing" step 2; spec §7, §8; OQ-1, OQ-4, OQ-10, OQ-21, OQ-30).

Each step reads Ledger, Prices, Asset and Portfolio through their ``public.py`` readers, built on
the date's Unit of Work, so every read sees the date's transaction. A step raises on a technical
problem; the processor turns that into the chain's failure on the date.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerEntry, LedgerReader
from di1.modules.pnl.public import (
    AssetPnLCalculator,
    AssetPnLResult,
    MissingReferencePrice,
    PnLTrade,
    PortfolioPnLCalculator,
)
from di1.modules.portfolio.public import (
    AssetValuationInput,
    CashBalance,
    CashCalculator,
    PortfolioReader,
    PortfolioResultsWriter,
    PositionsEngine,
    PositionState,
    Trade,
    ValuationCalculator,
    is_past_maturity,
    reference_pu_on,
)
from di1.modules.prices.public import PriceReader
from di1.modules.processing.application.interfaces.repositories import IssueRecord, IssueType
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.decimals import financial_context

ONE_DAY = timedelta(days=1)
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DayReaders:
    """The other modules' readers on one date's session."""

    ledger: LedgerReader
    prices: PriceReader
    assets: AssetReader
    portfolio: PortfolioReader


ReadersFactory = Callable[[UnitOfWork], DayReaders]
"""Builds the readers on a Unit of Work's session (the composition wires each module's
``dependencies`` factory)."""


class ChainDataError(RuntimeError):
    """The facts do not allow computing the date (a technical failure of the chain), e.g. a
    processed D−1 with no published rows, or a traded asset that does not exist."""


def trade_of(record: LedgerEntry) -> Trade:
    """Ledger's trade as the portfolio chains read it (interfaces.md "Portfolio")."""
    assert record.asset_id is not None and record.signed_quantity is not None
    assert record.execution_pu is not None and record.execution_rate is not None
    return Trade(
        asset_id=record.asset_id,
        trade_date=record.entry_date,
        trade_time=record.entry_time,
        seq=record.seq,
        signed_quantity=record.signed_quantity,
        execution_pu=record.execution_pu,
        execution_rate=record.execution_rate,
    )


def cash_totals(movements: Sequence[LedgerEntry]) -> tuple[Decimal, Decimal]:
    """The day's deposits and withdrawals, both as positive totals (OQ-24: an amount is signed,
    positive for an aporte, negative for a retirada)."""
    deposits = withdrawals = ZERO
    with financial_context():
        for movement in movements:
            assert movement.cash_amount is not None
            if movement.cash_amount > 0:
                deposits += movement.cash_amount
            else:
                withdrawals -= movement.cash_amount
    return deposits, withdrawals


async def process_cash_day(
    day: date,
    *,
    zero_state: bool,
    readers: DayReaders,
    writer: PortfolioResultsWriter,
    uow: UnitOfWork,
    other_chain_processed: bool,
) -> None:
    """``cash[D] = cash[D−1] − Σ(q × PU_exec) + deposits − withdrawals`` (spec §7.3), from the
    zero state or the published D−1 balance. The cash chain raises no Pendência (OQ-31)."""
    if zero_state:
        previous = CashBalance.zero(day - ONE_DAY)
    else:
        published = await readers.portfolio.get_previous_cash(day)
        if published is None:
            raise ChainDataError(f"the cash of {day - ONE_DAY} is processed but not published")
        previous = published
    trades = [trade_of(t) for t in await readers.ledger.get_trades(day, day)]
    deposits, withdrawals = cash_totals(await readers.ledger.get_cash_movements(day, day))
    cash_day = CashCalculator().calculate_day(previous, trades, deposits, withdrawals, day)
    await writer.write_cash_day(cash_day, uow=uow, other_chain_processed=other_chain_processed)


async def process_positions_day(
    day: date,
    *,
    zero_state: bool,
    readers: DayReaders,
    writer: PortfolioResultsWriter,
    uow: UnitOfWork,
    other_chain_processed: bool,
) -> list[IssueRecord]:
    """Positions, valuation and P&L of D for every expected asset (OQ-10), written through the
    writer; returns D's Pendências: a missing exact-date reference price (D, or D−1 when Q[D−1]
    ≠ 0, OQ-4) and an open position after maturity (OQ-1)."""
    previous_day = day - ONE_DAY
    previous_cumulative: Decimal | None
    if zero_state:
        state, previous_cumulative = PositionState.zero(previous_day), ZERO
    else:
        published = await readers.portfolio.get_previous_positions(day)
        if published is None:
            raise ChainDataError(f"the positions of {previous_day} are processed but not published")
        state, previous_cumulative = published.state, published.cumulative_pnl
    trades = [trade_of(t) for t in await readers.ledger.get_trades(day, day)]
    positions_day = PositionsEngine().calculate_day(state, trades, day)

    asset_ids = [p.asset_id for p in positions_day.positions]
    maturities = await _maturities(readers.assets, asset_ids)
    prices = await readers.prices.get(asset_ids, {previous_day, day}) if asset_ids else {}

    def reference_pu(asset_id: UUID, on: date) -> Decimal | None:
        price = prices.get((asset_id, on))
        return reference_pu_on(on, maturities[asset_id], None if price is None else price.pu)

    valuation_inputs: list[AssetValuationInput] = []
    asset_pnl: dict[UUID, AssetPnLResult] = {}
    issues: list[IssueRecord] = []
    for position in positions_day.positions:
        asset_id, maturity = position.asset_id, maturities[position.asset_id]
        current = None if is_past_maturity(day, maturity) else prices.get((asset_id, day))
        valuation_inputs.append(
            AssetValuationInput(
                asset_id=asset_id,
                quantity=position.quantity,
                maturity_date=maturity,
                reference_pu=None if current is None else current.pu,
            )
        )
        result = AssetPnLCalculator().calculate(
            position.previous_quantity,
            [PnLTrade(t.signed_quantity, t.execution_pu) for t in position.trades],
            reference_pu(asset_id, previous_day),
            reference_pu(asset_id, day),
        )
        asset_pnl[asset_id] = result
        needed = {
            previous_day if missing is MissingReferencePrice.PREVIOUS else day
            for missing in result.missing_prices
        }
        issues.extend(
            IssueRecord(IssueType.MISSING_REFERENCE_PRICE, asset_id, day, required)
            for required in sorted(needed)
        )
        if is_past_maturity(day, maturity) and position.quantity != 0:
            issues.append(IssueRecord(IssueType.EXPIRED_OPEN_POSITION, asset_id, day, None))

    valuation = ValuationCalculator().calculate_day(day, valuation_inputs)
    pnl = PortfolioPnLCalculator().aggregate(set(asset_ids), asset_pnl, previous_cumulative)
    await writer.write_positions_day(
        positions_day,
        valuation,
        asset_pnl,
        pnl,
        uow=uow,
        other_chain_processed=other_chain_processed,
    )
    return issues


async def _maturities(assets: AssetReader, asset_ids: Sequence[UUID]) -> dict[UUID, date]:
    if not asset_ids:
        return {}
    instruments = await assets.get_instruments(asset_ids)
    maturities: dict[UUID, date] = {}
    for asset_id in asset_ids:
        instrument = instruments.get(asset_id)
        if instrument is None or instrument.maturity_date is None:
            raise ChainDataError(f"asset {asset_id} has no instrument with a maturity")
        maturities[asset_id] = instrument.maturity_date
    return maturities
