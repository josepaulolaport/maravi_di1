"""Daily portfolio accounting: signed positions, average entry PU and rate, and cash (spec §7).

Pure and deterministic. One call computes one calendar day from the previous day's closing state,
that day's trades and its deposit and withdrawal totals. Cash movements are Ledger facts
(spec §6.2): Portfolio receives only the day's totals, summed by the caller. Reference prices are
not an input: quantities, averages and cash never depend on them (spec §7.2, §8.3), and P&L is
never posted to cash (spec §7.3).

Ledger owns trades and cash movements. ``Trade`` below is Portfolio's own input view of a trade,
holding only what accounting reads; Portfolio's application layer maps Ledger's public
``TradeRecord`` onto it (ports and adapters).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

from di1.shared.decimals import financial_context, quantize_pu, quantize_rate

ONE_DAY = timedelta(days=1)
ZERO = Decimal("0")


class AccountingError(ValueError):
    """Input the accounting engine cannot process: a skipped day, a misdated trade, or a value
    outside the bounds the engine relies on."""


@dataclass(frozen=True)
class Trade:
    """What accounting reads from a Ledger trade. ``signed_quantity`` is positive for a buy and
    negative for a sell; ``execution_pu`` and ``execution_rate`` are the execution price, never a
    reference price (spec §4.2)."""

    asset_id: UUID
    trade_date: date
    trade_time: time
    seq: int
    signed_quantity: int
    execution_pu: Decimal
    execution_rate: Decimal

    def __post_init__(self) -> None:
        if self.signed_quantity == 0:
            raise AccountingError("a trade quantity cannot be zero")

    @property
    def order_key(self) -> tuple[date, time, int]:
        """Chronological order of trades: (trade_date, trade_time, seq) (OQ-13)."""
        return (self.trade_date, self.trade_time, self.seq)


@dataclass(frozen=True)
class OpenPosition:
    """A non-zero position carried from one day to the next."""

    asset_id: UUID
    quantity: int
    average_entry_pu: Decimal
    average_entry_rate: Decimal

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise AccountingError("a carried position cannot be flat")


@dataclass(frozen=True)
class AccountingState:
    """The closing accounting state of ``as_of``: cash and the open positions, by asset id."""

    as_of: date
    cash_balance: Decimal
    positions: tuple[OpenPosition, ...] = field(default=())

    def __post_init__(self) -> None:
        asset_ids = [p.asset_id for p in self.positions]
        if len(set(asset_ids)) != len(asset_ids):
            raise AccountingError("a state holds at most one position per asset")
        object.__setattr__(self, "positions", tuple(sorted(self.positions, key=_by_asset)))

    @classmethod
    def zero(cls, as_of: date) -> AccountingState:
        """The starting state: zero cash and no positions (spec §7.1)."""
        return cls(as_of=as_of, cash_balance=Decimal("0"))


@dataclass(frozen=True)
class PositionDay:
    """One expected asset on one day (OQ-10): held yesterday or traded today.

    The averages are rounded at the day's close as stored: PU to 10 places, rate to 12 (OQ-3).
    The next day starts from these rounded values, so a range computed in one job equals the same
    days computed in several jobs that each read the previous day back from storage. Within the
    day, trades compound at full precision. A flat closing position has quantity 0 and no average
    (``None``). ``trades`` are the day's trades of this asset in the order they were applied; a
    trade that crosses zero stays whole.
    """

    asset_id: UUID
    previous_quantity: int
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None
    trades: tuple[Trade, ...]


@dataclass(frozen=True)
class AccountingDay:
    """The accounting result of one calendar day.

    ``trades_cash_flow`` is ``−Σ(signed_qty × execution_PU)``; ``cash_balance`` is
    ``previous_cash_balance + trades_cash_flow + deposits − withdrawals`` (spec §7.3).
    """

    date: date
    previous_cash_balance: Decimal
    trades_cash_flow: Decimal
    deposits: Decimal
    withdrawals: Decimal
    cash_balance: Decimal
    positions: tuple[PositionDay, ...]

    def closing_state(self) -> AccountingState:
        """The state the next day starts from: flat positions are dropped."""
        carried = []
        for p in self.positions:
            if p.quantity == 0:
                continue
            if p.average_entry_pu is None or p.average_entry_rate is None:
                # Unreachable: _Running sets an average on every opening trade.
                raise AccountingError(f"open position {p.asset_id} has no average entry price")
            carried.append(
                OpenPosition(
                    asset_id=p.asset_id,
                    quantity=p.quantity,
                    average_entry_pu=p.average_entry_pu,
                    average_entry_rate=p.average_entry_rate,
                )
            )
        return AccountingState(
            as_of=self.date, cash_balance=self.cash_balance, positions=tuple(carried)
        )


class PortfolioAccounting:
    """The daily accounting engine (interfaces.md "Portfolio")."""

    def calculate_day(
        self,
        previous_state: AccountingState,
        trades: Sequence[Trade],
        deposits: Decimal,
        withdrawals: Decimal,
        date: date,
    ) -> AccountingDay:
        """Apply ``date``'s trades, in (trade_date, trade_time, seq) order and never netted, and
        its deposit and withdrawal totals (each ``0`` when there are none) to the previous day's
        closing state."""
        if previous_state.as_of != date - ONE_DAY:
            raise AccountingError(
                f"the previous state must be of {date - ONE_DAY}, not {previous_state.as_of}"
            )
        day_trades = sorted(trades, key=lambda t: t.order_key)
        if any(t.trade_date != date for t in day_trades):
            raise AccountingError(f"every trade must be dated {date}")
        if deposits < 0 or withdrawals < 0:
            raise AccountingError("deposit and withdrawal totals cannot be negative")
        # A "-0" total passes the check above; store it unsigned so it never serializes as "-0".
        deposits, withdrawals = deposits.copy_abs(), withdrawals.copy_abs()

        with financial_context():
            positions = _positions_of_day(previous_state.positions, day_trades)
            # 0 − Σ rather than −Σ: an empty day must not yield a negative zero.
            trades_cash_flow = Decimal("0") - sum(
                (t.signed_quantity * t.execution_pu for t in day_trades), Decimal("0")
            )
            cash_balance = previous_state.cash_balance + trades_cash_flow + deposits - withdrawals

        return AccountingDay(
            date=date,
            previous_cash_balance=previous_state.cash_balance,
            trades_cash_flow=trades_cash_flow,
            deposits=deposits,
            withdrawals=withdrawals,
            cash_balance=cash_balance,
            positions=positions,
        )

    def calculate_range(
        self,
        previous_state: AccountingState,
        trades: Sequence[Trade],
        deposits: Mapping[date, Decimal],
        withdrawals: Mapping[date, Decimal],
        end_date: date,
    ) -> tuple[AccountingDay, ...]:
        """Every calendar day from ``previous_state.as_of + 1`` to ``end_date``, each starting
        from the previous day's closing state (spec §7.1). ``deposits`` and ``withdrawals`` hold
        the daily totals; a missing date means none."""
        start_date = previous_state.as_of + ONE_DAY
        if end_date < previous_state.as_of:
            raise AccountingError(f"the range ends on {end_date}, before {previous_state.as_of}")
        trades_by_date: dict[date, list[Trade]] = {}
        for t in trades:
            trades_by_date.setdefault(t.trade_date, []).append(t)
        outside = [
            d for d in (*trades_by_date, *deposits, *withdrawals) if not start_date <= d <= end_date
        ]
        if outside:
            raise AccountingError(
                f"events dated {min(outside)} are outside {start_date}..{end_date}"
            )

        days: list[AccountingDay] = []
        state, current = previous_state, start_date
        while current <= end_date:
            day = self.calculate_day(
                state,
                trades_by_date.get(current, ()),
                deposits.get(current, ZERO),
                withdrawals.get(current, ZERO),
                current,
            )
            days.append(day)
            state, current = day.closing_state(), current + ONE_DAY
        return tuple(days)


@dataclass
class _Running:
    quantity: int
    average_entry_pu: Decimal | None
    average_entry_rate: Decimal | None

    def apply(self, trade: Trade) -> None:
        previous, traded = self.quantity, trade.signed_quantity
        current = previous + traded
        if previous == 0 or (previous > 0) == (traded > 0):
            # Open or increase: weight PU and rate separately by absolute quantity (spec §7.2).
            self.average_entry_pu = _weighted(
                previous, self.average_entry_pu, traded, trade.execution_pu
            )
            self.average_entry_rate = _weighted(
                previous, self.average_entry_rate, traded, trade.execution_rate
            )
        elif current == 0:
            self.average_entry_pu = self.average_entry_rate = None
        elif (current > 0) != (previous > 0):
            # Crossing zero: the old position closes, the remainder opens at the trade's PU/rate.
            self.average_entry_pu, self.average_entry_rate = (
                trade.execution_pu,
                trade.execution_rate,
            )
        # Otherwise a partial reduction: the average is kept.
        self.quantity = current


def _weighted(quantity: int, average: Decimal | None, added: int, price: Decimal) -> Decimal:
    if quantity == 0 or average is None:
        return price
    held, extra = abs(quantity), abs(added)
    return (held * average + extra * price) / (held + extra)


def _positions_of_day(
    carried: Sequence[OpenPosition], day_trades: Sequence[Trade]
) -> tuple[PositionDay, ...]:
    running = {
        p.asset_id: _Running(p.quantity, p.average_entry_pu, p.average_entry_rate) for p in carried
    }
    previous_quantity = {p.asset_id: p.quantity for p in carried}
    applied: dict[UUID, list[Trade]] = {}
    for t in day_trades:
        running.setdefault(t.asset_id, _Running(0, None, None)).apply(t)
        applied.setdefault(t.asset_id, []).append(t)
    return tuple(
        PositionDay(
            asset_id=asset_id,
            previous_quantity=previous_quantity.get(asset_id, 0),
            quantity=position.quantity,
            average_entry_pu=_maybe(quantize_pu, position.average_entry_pu),
            average_entry_rate=_maybe(quantize_rate, position.average_entry_rate),
            trades=tuple(applied.get(asset_id, ())),
        )
        for asset_id, position in sorted(running.items(), key=lambda item: item[0])
    )


def _maybe(quantize: Callable[[Decimal], Decimal], value: Decimal | None) -> Decimal | None:
    return None if value is None else quantize(value)


def _by_asset(position: OpenPosition) -> UUID:
    return position.asset_id
