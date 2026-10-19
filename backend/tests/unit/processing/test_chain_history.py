"""The zero state of each chain, read from the Ledger (OQ-22, OQ-26 item 3): positions have
nothing before them without a trade; cash, without an entry of either type."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from di1.modules.ledger.public import CashMovementRecord, TradeRecord
from di1.modules.processing.application.interfaces.repositories import ProcessingChain
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind

CREATED = datetime(2026, 10, 1, 9, 0, tzinfo=SAO_PAULO)


class FakeLedger:
    def __init__(
        self, trades: list[TradeRecord] | None = None, cash: list[CashMovementRecord] | None = None
    ) -> None:
        self.trades = trades or []
        self.cash = cash or []

    async def get_trades(self, start_date: date, end_date: date) -> list[TradeRecord]:
        return [t for t in self.trades if start_date <= t.trade_date <= end_date]

    async def get_cash_movements(
        self, start_date: date, end_date: date
    ) -> list[CashMovementRecord]:
        return [m for m in self.cash if start_date <= m.movement_date <= end_date]


def _trade(day: date) -> TradeRecord:
    return TradeRecord(
        id=uuid4(),
        asset_id=uuid4(),
        trade_date=day,
        trade_time=time(10, 0),
        seq=1,
        signed_quantity=10,
        execution_pu=Decimal("90000"),
        execution_rate=Decimal("0.10"),
        input_kind=InputKind.PU,
        created_at=CREATED,
    )


def _deposit(day: date) -> CashMovementRecord:
    return CashMovementRecord(
        id=uuid4(),
        movement_date=day,
        movement_time=time(9, 0),
        seq=2,
        amount=Decimal("1000.00"),
        created_at=CREATED,
    )


async def test_oq26_a_deposit_ends_only_the_cash_zero_state() -> None:
    history = LedgerChainHistory(FakeLedger(cash=[_deposit(date(2026, 10, 5))]))

    assert await history.has_entries_on_or_before(ProcessingChain.CASH, date(2026, 10, 5))
    assert not await history.has_entries_on_or_before(ProcessingChain.CASH, date(2026, 10, 4))
    assert not await history.has_entries_on_or_before(ProcessingChain.POSITIONS, date(2026, 10, 30))


async def test_oq26_a_trade_ends_the_zero_state_of_both_chains() -> None:
    history = LedgerChainHistory(FakeLedger(trades=[_trade(date(2026, 10, 5))]))

    for chain in ProcessingChain:
        assert await history.has_entries_on_or_before(chain, date(2026, 10, 5))
        assert not await history.has_entries_on_or_before(chain, date(2026, 10, 4))
