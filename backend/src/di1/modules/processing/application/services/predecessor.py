"""The predecessor rule, per day (interfaces.md "Predecessor rule, per day"; OQ-26 item 8,
OQ-31 item 4, OQ-37 item 4, OQ-40 item 5): the one copy the preview and the run share."""

from __future__ import annotations

from datetime import date

from di1.modules.processing.application.ports import ChainHistory, DateStatusRepository
from di1.modules.processing.domain.date_status import Chain, ChainStatus
from di1.modules.processing.domain.predecessor import PredecessorState


async def read_predecessor(
    chain: Chain,
    day_before: date,
    stored: ChainStatus | None,
    *,
    date_statuses: DateStatusRepository,
    history: ChainHistory,
) -> PredecessorState:
    """The state of ``day_before`` for ``chain``, given its stored status there (``None``
    without one). Lazy: each fact is read only when the rule needs it, in this order.

    1. A status stored on D−1 is the state, whatever it is (a FAILED D−1 fails D).
    2. Otherwise a status on an earlier date makes D−1 a gap: NOT_PROCESSED, and the Ledger is
       not asked (OQ-37 item 4).
    3. Otherwise an entry of the chain on or before D−1 means it was never processed:
       NOT_PROCESSED; with none, the chain is in its ZERO_STATE.
    """
    if stored is not None:
        return PredecessorState(stored.value)
    if await date_statuses.has_status_before(chain, day_before):
        return PredecessorState.NOT_PROCESSED
    if await history.has_entries_on_or_before(chain, day_before):
        return PredecessorState.NOT_PROCESSED
    return PredecessorState.ZERO_STATE
