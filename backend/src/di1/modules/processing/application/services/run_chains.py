"""One date of each chain: read the facts, run the pure calculators, write the published rows
(interfaces.md "Processing" step 2; spec §7, §8; OQ-1, OQ-4, OQ-10, OQ-21, OQ-30).

Each step reads Ledger, Prices, Asset and Portfolio and writes Portfolio through their
``public.py`` ports (`ChainPorts`), built on the date's Unit of Work, so every read sees the
date's transaction. A step raises on a technical
problem; the processor turns that into the chain's failure on the date.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerEntry
from di1.modules.pnl.public import (
    AssetPnLResult,
    MissingReferencePrice,
    PnLTrade,
    aggregate_pnl,
    calculate_asset_pnl,
)
from di1.modules.portfolio.public import (
    AssetValuationInput,
    CashBalance,
    PositionState,
    Trade,
    calculate_cash_day,
    calculate_positions_day,
    is_past_maturity,
    reference_pu_on,
    value_positions,
)
from di1.modules.processing.application.ports import ChainPorts
from di1.modules.processing.domain.errors import ProcessingError
from di1.modules.processing.domain.issues import IssueRecord, IssueType
from di1.shared.calendar import ONE_DAY
from di1.shared.decimals import ZERO, financial_context


def trade_of(record: LedgerEntry) -> Trade:
    """Ledger's trade as the portfolio chains read it (interfaces.md "Portfolio")."""
    if (
        record.asset_id is None
        or record.signed_quantity is None
        or record.execution_pu is None
        or record.execution_rate is None
    ):
        raise ProcessingError(f"trade {record.id} lacks its contract, quantity, PU or rate")
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
            if movement.cash_amount is None:
                raise ProcessingError(f"cash movement {movement.id} has no amount")
            if movement.cash_amount > 0:
                deposits += movement.cash_amount
            else:
                withdrawals -= movement.cash_amount
    return deposits, withdrawals


async def process_cash_day(
    day: date,
    *,
    zero_state: bool,
    ports: ChainPorts,
) -> None:
    """``cash[D] = cash[D−1] − Σ(q × PU_exec) + deposits − withdrawals`` (spec §7.3), from the
    zero state or the published D−1 balance. The cash chain raises no Pendência (OQ-31)."""
    if zero_state:
        previous = CashBalance.zero(day - ONE_DAY)
    else:
        published = await ports.portfolio.get_previous_cash(day)
        if published is None:
            raise ProcessingError(f"the cash of {day - ONE_DAY} is processed but not published")
        previous = published
    trades = [trade_of(t) for t in await ports.ledger.get_trades(day, day)]
    deposits, withdrawals = cash_totals(await ports.ledger.get_cash_movements(day, day))
    cash_day = calculate_cash_day(previous, trades, deposits, withdrawals, day)
    await ports.writer.write_cash_day(cash_day)


async def process_positions_day(
    day: date,
    *,
    zero_state: bool,
    ports: ChainPorts,
) -> list[IssueRecord]:
    """Positions, valuation and P&L of D for every expected asset (OQ-10), written through the
    writer; returns D's Pendências: a missing exact-date reference price (D, or D−1 when Q[D−1]
    ≠ 0, OQ-4) and an open position after maturity (OQ-1)."""
    previous_day = day - ONE_DAY
    previous_cumulative: Decimal | None
    if zero_state:
        state, previous_cumulative = PositionState.zero(previous_day), ZERO
    else:
        published = await ports.portfolio.get_previous_positions(day)
        if published is None:
            raise ProcessingError(
                f"the positions of {previous_day} are processed but not published"
            )
        state, previous_cumulative = published.state, published.cumulative_pnl
    trades = [trade_of(t) for t in await ports.ledger.get_trades(day, day)]
    positions_day = calculate_positions_day(state, trades, day)

    asset_ids = [p.asset_id for p in positions_day.positions]
    maturities = await _maturities(ports.assets, asset_ids)
    prices = await ports.prices.get(asset_ids, {previous_day, day}) if asset_ids else {}

    def reference_pu(asset_id: UUID, on: date) -> Decimal | None:
        """The one resolution of the maturity rule (OQ-1): the exact-date price up to maturity,
        0 after it, whatever price exists."""
        price = prices.get((asset_id, on))
        return reference_pu_on(on, maturities[asset_id], None if price is None else price.pu)

    valuation_inputs: list[AssetValuationInput] = []
    asset_pnl: dict[UUID, AssetPnLResult] = {}
    issues: list[IssueRecord] = []
    for position in positions_day.positions:
        asset_id = position.asset_id
        current_pu = reference_pu(asset_id, day)
        valuation_inputs.append(AssetValuationInput(asset_id, position.quantity, current_pu))
        result = calculate_asset_pnl(
            position.previous_quantity,
            [PnLTrade(t.signed_quantity, t.execution_pu) for t in position.trades],
            reference_pu(asset_id, previous_day),
            current_pu,
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
        if is_past_maturity(day, maturities[asset_id]) and position.quantity != 0:
            issues.append(IssueRecord(IssueType.EXPIRED_OPEN_POSITION, asset_id, day, None))

    valuation = value_positions(day, valuation_inputs)
    pnl = aggregate_pnl(set(asset_ids), asset_pnl, previous_cumulative)
    await ports.writer.write_positions_day(positions_day, valuation, asset_pnl, pnl)
    return issues


async def _maturities(assets: AssetReader, asset_ids: Sequence[UUID]) -> dict[UUID, date]:
    if not asset_ids:
        return {}
    instruments = await assets.get_instruments(asset_ids)
    maturities: dict[UUID, date] = {}
    for asset_id in asset_ids:
        instrument = instruments.get(asset_id)
        if instrument is None or instrument.maturity_date is None:
            raise ProcessingError(f"asset {asset_id} has no instrument with a maturity")
        maturities[asset_id] = instrument.maturity_date
    return maturities
