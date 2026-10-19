"""The cash chain: cash[D] = cash[D−1] − Σ(signed_qty × execution_PU) + deposits − withdrawals.

Spec §7.3. Independent of the positions chain: it reads trades and the day's deposit and withdrawal
totals directly, never position state or reference prices, so the cash effect of a trade lives
here only, and P&L can never reach cash. Cash movements are Ledger facts (spec §6.2); the caller
sums them into daily totals. Money is kept exact (OQ-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from di1.modules.portfolio.domain.errors import AccountingError, require_next_day
from di1.modules.portfolio.domain.trade import Trade, day_trades
from di1.shared.decimals import financial_context

ZERO = Decimal("0")


@dataclass(frozen=True)
class CashBalance:
    """The cash balance at the close of ``as_of``."""

    as_of: date
    balance: Decimal

    @classmethod
    def zero(cls, as_of: date) -> CashBalance:
        """The starting state: zero cash (spec §7.1)."""
        return cls(as_of=as_of, balance=ZERO)


@dataclass(frozen=True)
class CashDay:
    """One day of cash. ``trades_cash_flow`` is ``−Σ(signed_qty × execution_PU)``."""

    date: date
    previous_cash_balance: Decimal | None
    trades_cash_flow: Decimal
    deposits: Decimal
    withdrawals: Decimal
    cash_balance: Decimal

    def closing_balance(self) -> CashBalance:
        return CashBalance(as_of=self.date, balance=self.cash_balance)


class CashCalculator:
    """The cash chain, callable on its own (Processing may run cash without positions)."""

    def calculate_day(
        self,
        previous_balance: CashBalance,
        trades: Sequence[Trade],
        deposits: Decimal,
        withdrawals: Decimal,
        date: date,
    ) -> CashDay:
        """``deposits`` and ``withdrawals`` are the day's totals, ``0`` when there are none."""
        require_next_day(previous_balance.as_of, date)
        ordered = day_trades(trades, date)
        if deposits < 0 or withdrawals < 0:
            raise AccountingError("deposit and withdrawal totals cannot be negative")
        # A "-0" total passes the check above; store it unsigned so it never serializes as "-0".
        deposits, withdrawals = deposits.copy_abs(), withdrawals.copy_abs()
        with financial_context():
            # 0 − Σ rather than −Σ: an empty day must not yield a negative zero.
            trades_cash_flow = ZERO - sum(
                (t.signed_quantity * t.execution_pu for t in ordered), ZERO
            )
            cash_balance = previous_balance.balance + trades_cash_flow + deposits - withdrawals
        return CashDay(
            date=date,
            previous_cash_balance=previous_balance.balance,
            trades_cash_flow=trades_cash_flow,
            deposits=deposits,
            withdrawals=withdrawals,
            cash_balance=cash_balance,
        )
