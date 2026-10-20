"""The positions chain: signed quantities and average costs per asset, day by day (spec §7.2).

Trades are applied one at a time in (trade_date, trade_time, seq) order, never netted. A trade
that crosses zero stays one row. Rows exist exactly for the expected assets (OQ-10): held
yesterday or traded today, including quantity 0 after a full close or a same-day round trip.
This chain computes no cash (``cash.py`` does) and reads no reference price (``valuation.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from di1.modules.portfolio.domain.average_cost import (
    closing_average_pu,
    closing_average_rate,
    next_average,
)
from di1.modules.portfolio.domain.errors import PortfolioError, require_next_day
from di1.modules.portfolio.domain.trade import Trade, day_trades


@dataclass(frozen=True)
class OpenPosition:
    """A non-zero position carried from one day to the next."""

    asset_id: UUID
    quantity: int
    average_entry_pu: Decimal
    average_entry_rate: Decimal

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise PortfolioError("a carried position cannot be flat")


@dataclass(frozen=True)
class PositionState:
    """The open positions at the close of ``as_of``, by asset id."""

    as_of: date
    positions: tuple[OpenPosition, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", _sorted_unique(self.positions))

    @classmethod
    def zero(cls, as_of: date) -> PositionState:
        """The starting state: no positions (spec §7.1)."""
        return cls(as_of=as_of)


@dataclass(frozen=True)
class PositionDay:
    """One expected asset on one day (OQ-10).

    A flat closing position has quantity 0 and no average (``None``). The averages are the day's
    closing values as stored (``average_cost.py``). ``trades`` are the day's trades of this asset
    in the order they were applied; a trade that crosses zero stays whole.
    """

    asset_id: UUID
    previous_quantity: int
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None
    trades: tuple[Trade, ...]


@dataclass(frozen=True)
class PositionsDay:
    """The positions of every expected asset on ``date``, in asset id order."""

    date: date
    positions: tuple[PositionDay, ...]

    def closing_state(self) -> PositionState:
        """The state the next day starts from: flat positions are dropped."""
        carried = []
        for p in self.positions:
            if p.quantity == 0:
                continue
            if p.average_entry_pu is None or p.average_entry_rate is None:
                # Unreachable: every opening trade sets an average.
                raise PortfolioError(f"open position {p.asset_id} has no average entry price")
            carried.append(
                OpenPosition(
                    asset_id=p.asset_id,
                    quantity=p.quantity,
                    average_entry_pu=p.average_entry_pu,
                    average_entry_rate=p.average_entry_rate,
                )
            )
        return PositionState(as_of=self.date, positions=tuple(carried))


def calculate_positions_day(
    previous_state: PositionState, trades: Sequence[Trade], date: date
) -> PositionsDay:
    """One day of the positions chain, callable on its own (Processing may run positions without
    cash)."""
    require_next_day(previous_state.as_of, date)
    ordered = day_trades(trades, date)
    running = {p.asset_id: _Running.of(p) for p in previous_state.positions}
    applied: dict[UUID, list[Trade]] = {}
    for t in ordered:
        running.setdefault(t.asset_id, _Running(0, 0, None, None)).apply(t)
        applied.setdefault(t.asset_id, []).append(t)
    return PositionsDay(
        date=date,
        positions=tuple(
            PositionDay(
                asset_id=asset_id,
                previous_quantity=r.previous_quantity,
                quantity=r.quantity,
                average_entry_pu=closing_average_pu(r.average_entry_pu),
                average_entry_rate=closing_average_rate(r.average_entry_rate),
                trades=tuple(applied.get(asset_id, ())),
            )
            for asset_id, r in sorted(running.items(), key=lambda item: item[0])
        ),
    )


@dataclass
class _Running:
    previous_quantity: int
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None

    @classmethod
    def of(cls, position: OpenPosition) -> _Running:
        return cls(
            position.quantity,
            position.quantity,
            position.average_entry_pu,
            position.average_entry_rate,
        )

    def apply(self, trade: Trade) -> None:
        held, traded = self.quantity, trade.signed_quantity
        self.average_entry_pu = next_average(
            held, self.average_entry_pu, traded, trade.execution_pu
        )
        self.average_entry_rate = next_average(
            held, self.average_entry_rate, traded, trade.execution_rate
        )
        self.quantity = held + traded


def _sorted_unique(positions: tuple[OpenPosition, ...]) -> tuple[OpenPosition, ...]:
    asset_ids = [p.asset_id for p in positions]
    if len(set(asset_ids)) != len(asset_ids):
        raise PortfolioError("a state holds at most one position per asset")
    return tuple(sorted(positions, key=lambda p: p.asset_id))
