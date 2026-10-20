"""The zero state of each chain, read from the Ledger's existence read (OQ-26 item 3, OQ-37):
positions have nothing before them without a trade; cash, without an entry of either type. The
dates and types the Ledger matches are tested on PostgreSQL in
``tests/integration/ledger/test_ledger_persistence.py``."""

from __future__ import annotations

from datetime import date

from di1.modules.ledger.public import EntryType, LedgerEntry
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.domain.date_status import Chain


class FakeLedger:
    """Answers whether entries exist with a fixed answer per entry type, and records the asks."""

    def __init__(self, answers: dict[EntryType | None, bool]) -> None:
        self.answers = answers
        self.asked: list[tuple[date, EntryType | None]] = []

    async def get_trades(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return []

    async def get_cash_movements(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return []

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        self.asked.append((day, entry_type))
        return self.answers[entry_type]


async def test_oq37_positions_ask_for_trades_and_cash_for_any_entry() -> None:
    ledger = FakeLedger({EntryType.TRADE: True, None: False})
    history = LedgerChainHistory(ledger)

    positions = await history.has_entries_on_or_before(Chain.POSITIONS, date(2026, 10, 4))
    cash = await history.has_entries_on_or_before(Chain.CASH, date(2026, 10, 4))

    assert ledger.asked == [(date(2026, 10, 4), EntryType.TRADE), (date(2026, 10, 4), None)]
    assert (positions, cash) == (True, False)  # the Ledger's answer, as is
