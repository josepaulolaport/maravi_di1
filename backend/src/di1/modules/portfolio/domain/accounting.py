"""A convenience that runs the positions and cash chains together for the same days (spec §7).

The chains stay independent and callable on their own (``positions.py``, ``cash.py``), so
Processing can run cash, positions or both. This module only pairs their results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from di1.modules.portfolio.domain.cash import CashBalance, CashCalculator, CashDay
from di1.modules.portfolio.domain.errors import AccountingError
from di1.modules.portfolio.domain.positions import (
    OpenPosition,
    PositionDay,
    PositionsDay,
    PositionsEngine,
    PositionState,
)
from di1.modules.portfolio.domain.trade import Trade

ZERO = Decimal("0")


@dataclass(frozen=True)
class AccountingState:
    """The closing cash balance and open positions of ``as_of``."""

    as_of: date
    cash_balance: Decimal
    positions: tuple[OpenPosition, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", self.position_state().positions)

    @classmethod
    def zero(cls, as_of: date) -> AccountingState:
        """The starting state: zero cash and no positions (spec §7.1)."""
        return cls(as_of=as_of, cash_balance=ZERO)

    def position_state(self) -> PositionState:
        return PositionState(as_of=self.as_of, positions=self.positions)

    def cash(self) -> CashBalance:
        return CashBalance(as_of=self.as_of, balance=self.cash_balance)


@dataclass(frozen=True)
class AccountingDay:
    """One day of both chains."""

    cash: CashDay
    positions_day: PositionsDay

    def __post_init__(self) -> None:
        if self.cash.date != self.positions_day.date:
            raise AccountingError("the cash and positions days must be the same date")

    @property
    def date(self) -> date:
        return self.cash.date

    @property
    def positions(self) -> tuple[PositionDay, ...]:
        return self.positions_day.positions

    @property
    def previous_cash_balance(self) -> Decimal:
        return self.cash.previous_cash_balance

    @property
    def trades_cash_flow(self) -> Decimal:
        return self.cash.trades_cash_flow

    @property
    def deposits(self) -> Decimal:
        return self.cash.deposits

    @property
    def withdrawals(self) -> Decimal:
        return self.cash.withdrawals

    @property
    def cash_balance(self) -> Decimal:
        return self.cash.cash_balance

    def closing_state(self) -> AccountingState:
        return AccountingState(
            as_of=self.date,
            cash_balance=self.cash_balance,
            positions=self.positions_day.closing_state().positions,
        )


class PortfolioAccounting:
    def __init__(
        self,
        positions: PositionsEngine | None = None,
        cash: CashCalculator | None = None,
    ) -> None:
        self._positions = positions or PositionsEngine()
        self._cash = cash or CashCalculator()

    def calculate_day(
        self,
        previous_state: AccountingState,
        trades: Sequence[Trade],
        deposits: Decimal,
        withdrawals: Decimal,
        date: date,
    ) -> AccountingDay:
        return AccountingDay(
            cash=self._cash.calculate_day(
                previous_state.cash(), trades, deposits, withdrawals, date
            ),
            positions_day=self._positions.calculate_day(
                previous_state.position_state(), trades, date
            ),
        )

    def calculate_range(
        self,
        previous_state: AccountingState,
        trades: Sequence[Trade],
        deposits: Mapping[date, Decimal],
        withdrawals: Mapping[date, Decimal],
        end_date: date,
    ) -> tuple[AccountingDay, ...]:
        cash_days = self._cash.calculate_range(
            previous_state.cash(), trades, deposits, withdrawals, end_date
        )
        position_days = self._positions.calculate_range(
            previous_state.position_state(), trades, end_date
        )
        return tuple(
            AccountingDay(cash=c, positions_day=p)
            for c, p in zip(cash_days, position_days, strict=True)
        )
