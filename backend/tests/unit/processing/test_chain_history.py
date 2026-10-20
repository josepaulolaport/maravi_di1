"""The zero state of each chain, read from the Ledger's existence read (OQ-26 item 3, OQ-37):
positions have nothing before them without a trade; cash, without an entry of either type."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from di1.modules.ledger.public import EntryType
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.domain.date_status import Chain
from tests.support.builders import ledger_cash, ledger_trade
from tests.support.fakes import FakeLedger


async def test_oq26_a_deposit_ends_only_the_cash_zero_state() -> None:
    history = LedgerChainHistory(FakeLedger(movements=[ledger_cash(date(2026, 10, 5), "1000")]))

    assert await history.has_entries_on_or_before(Chain.CASH, date(2026, 10, 5))
    assert not await history.has_entries_on_or_before(Chain.CASH, date(2026, 10, 4))
    assert not await history.has_entries_on_or_before(Chain.POSITIONS, date(2026, 10, 30))


async def test_oq26_a_trade_ends_the_zero_state_of_both_chains() -> None:
    history = LedgerChainHistory(
        FakeLedger(trades=[ledger_trade(uuid4(), date(2026, 10, 5), 10, "90000")])
    )

    for chain in Chain:
        assert await history.has_entries_on_or_before(chain, date(2026, 10, 5))
        assert not await history.has_entries_on_or_before(chain, date(2026, 10, 4))


async def test_oq37_positions_ask_for_trades_and_cash_for_any_entry() -> None:
    ledger = FakeLedger()
    history = LedgerChainHistory(ledger)

    await history.has_entries_on_or_before(Chain.POSITIONS, date(2026, 10, 4))
    await history.has_entries_on_or_before(Chain.CASH, date(2026, 10, 4))

    assert ledger.asked == [(date(2026, 10, 4), EntryType.TRADE), (date(2026, 10, 4), None)]
