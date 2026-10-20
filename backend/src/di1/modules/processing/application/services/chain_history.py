"""`ChainHistory` over `ledger.public.LedgerReader`: whether a chain is in its zero state
(OQ-26 item 3, OQ-32, OQ-37)."""

from __future__ import annotations

from datetime import date

from di1.modules.ledger.public import EntryType, LedgerReader
from di1.modules.processing.domain.date_status import Chain


class LedgerChainHistory:
    """`ChainHistory` through the Ledger's existence read (OQ-37)."""

    def __init__(self, ledger: LedgerReader) -> None:
        self._ledger = ledger

    async def has_entries_on_or_before(self, chain: Chain, day: date) -> bool:
        entry_type = EntryType.TRADE if chain is Chain.POSITIONS else None
        return await self._ledger.has_entries_on_or_before(day, entry_type=entry_type)
