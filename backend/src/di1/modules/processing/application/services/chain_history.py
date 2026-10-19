"""`ChainHistory` over `ledger.public.LedgerReader`: whether a chain is in its zero state
(OQ-22, OQ-26 item 3)."""

from __future__ import annotations

from datetime import date

from di1.modules.ledger.public import LedgerReader
from di1.modules.processing.application.interfaces.repositories import ProcessingChain


class LedgerChainHistory:
    """Satisfies `ChainHistory`. It reads the entries up to the day, since `LedgerReader` has no
    existence query; only the preview calls it, once per chain."""

    def __init__(self, ledger: LedgerReader) -> None:
        self._ledger = ledger

    async def has_entries_on_or_before(self, chain: ProcessingChain, day: date) -> bool:
        if await self._ledger.get_trades(date.min, day):
            return True
        if chain is ProcessingChain.POSITIONS:
            return False
        return bool(await self._ledger.get_cash_movements(date.min, day))
