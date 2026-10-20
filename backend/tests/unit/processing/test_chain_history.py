"""The zero state of each chain, read from the Ledger's existence read (OQ-26 item 3, OQ-37):
positions have nothing before them without a trade; cash, without an entry of either type. The
dates and types the Ledger matches are tested on PostgreSQL in
``tests/integration/ledger/test_ledger_persistence.py``."""

from __future__ import annotations

from datetime import date

from di1.modules.ledger.public import EntryType
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.domain.date_status import Chain
from tests.support.builders import ledger_cash
from tests.support.fakes import FakeLedger


async def test_oq37_positions_ask_for_trades_and_cash_for_any_entry() -> None:
    ledger = FakeLedger(movements=[ledger_cash(date(2026, 10, 4), "1000.00")])
    history = LedgerChainHistory(ledger)

    positions = await history.has_entries_on_or_before(Chain.POSITIONS, date(2026, 10, 4))
    cash = await history.has_entries_on_or_before(Chain.CASH, date(2026, 10, 4))

    assert ledger.asked == [(date(2026, 10, 4), EntryType.TRADE), (date(2026, 10, 4), None)]
    assert (positions, cash) == (False, True)  # the Ledger's answer for each type, as is
