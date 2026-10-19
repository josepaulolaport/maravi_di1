"""Ledger's public records onto Portfolio's domain inputs (ports and adapters).

Ledger owns trades and cash movements (spec §6); the positions and cash chains read their own
``Trade`` and the day's deposit and withdrawal totals.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from di1.modules.ledger.public import CashMovementRecord, TradeRecord
from di1.modules.portfolio.domain.errors import AccountingError
from di1.modules.portfolio.domain.trade import Trade
from di1.shared.decimals import financial_context


def trade_of(record: TradeRecord) -> Trade:
    return Trade(
        asset_id=record.asset_id,
        trade_date=record.trade_date,
        trade_time=record.trade_time,
        seq=record.seq,
        signed_quantity=record.signed_quantity,
        execution_pu=record.execution_pu,
        execution_rate=record.execution_rate,
    )


def daily_cash_totals(
    movements: Iterable[CashMovementRecord],
) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
    """The deposits and withdrawals of each date, both as positive totals. A movement's amount is
    signed: positive for an aporte, negative for a retirada (OQ-24)."""
    deposits: dict[date, Decimal] = {}
    withdrawals: dict[date, Decimal] = {}
    with financial_context():
        for m in movements:
            if m.amount > 0:
                deposits[m.movement_date] = deposits.get(m.movement_date, Decimal("0")) + m.amount
            elif m.amount == 0:
                raise AccountingError(f"cash movement {m.id} has a zero amount")
            else:
                withdrawals[m.movement_date] = (
                    withdrawals.get(m.movement_date, Decimal("0")) - m.amount
                )
    return deposits, withdrawals
