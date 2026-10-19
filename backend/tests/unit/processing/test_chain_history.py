"""The zero state of each chain, read from the Ledger's existence read (OQ-26 item 3, OQ-37):
positions have nothing before them without a trade; cash, without an entry of either type."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from di1.modules.ledger.public import EntryType, LedgerEntry
from di1.modules.processing.application.interfaces.repositories import ProcessingChain
from di1.modules.processing.application.services.chain_history import ChainHistory
from di1.shared.clock import SAO_PAULO
from di1.shared.input_kind import InputKind

CREATED = datetime(2026, 10, 1, 9, 0, tzinfo=SAO_PAULO)


class FakeLedger:
    def __init__(
        self, trades: list[LedgerEntry] | None = None, cash: list[LedgerEntry] | None = None
    ) -> None:
        self.trades = trades or []
        self.cash = cash or []
        self.asked: list[tuple[date, EntryType | None]] = []

    async def get_trades(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return [t for t in self.trades if start_date <= t.entry_date <= end_date]

    async def get_cash_movements(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return [m for m in self.cash if start_date <= m.entry_date <= end_date]

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        self.asked.append((day, entry_type))
        trades = any(t.entry_date <= day for t in self.trades)
        cash = any(m.entry_date <= day for m in self.cash)
        return trades if entry_type is EntryType.TRADE else trades or cash


def _trade(day: date) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.TRADE,
        entry_date=day,
        entry_time=time(10, 0),
        seq=1,
        created_at=CREATED,
        asset_id=uuid4(),
        signed_quantity=10,
        execution_pu=Decimal("90000"),
        execution_rate=Decimal("0.10"),
        input_kind=InputKind.PU,
        cash_amount=None,
    )


def _deposit(day: date) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        type=EntryType.CASH,
        entry_date=day,
        entry_time=time(9, 0),
        seq=2,
        created_at=CREATED,
        asset_id=None,
        signed_quantity=None,
        execution_pu=None,
        execution_rate=None,
        input_kind=None,
        cash_amount=Decimal("1000.00"),
    )


async def test_oq26_a_deposit_ends_only_the_cash_zero_state() -> None:
    history = ChainHistory(FakeLedger(cash=[_deposit(date(2026, 10, 5))]))

    assert await history.has_entries_on_or_before(ProcessingChain.CASH, date(2026, 10, 5))
    assert not await history.has_entries_on_or_before(ProcessingChain.CASH, date(2026, 10, 4))
    assert not await history.has_entries_on_or_before(ProcessingChain.POSITIONS, date(2026, 10, 30))


async def test_oq26_a_trade_ends_the_zero_state_of_both_chains() -> None:
    history = ChainHistory(FakeLedger(trades=[_trade(date(2026, 10, 5))]))

    for chain in ProcessingChain:
        assert await history.has_entries_on_or_before(chain, date(2026, 10, 5))
        assert not await history.has_entries_on_or_before(chain, date(2026, 10, 4))


async def test_oq37_positions_ask_for_trades_and_cash_for_any_entry() -> None:
    ledger = FakeLedger()
    history = ChainHistory(ledger)

    await history.has_entries_on_or_before(ProcessingChain.POSITIONS, date(2026, 10, 4))
    await history.has_entries_on_or_before(ProcessingChain.CASH, date(2026, 10, 4))

    assert ledger.asked == [(date(2026, 10, 4), EntryType.TRADE), (date(2026, 10, 4), None)]
