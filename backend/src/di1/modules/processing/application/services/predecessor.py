"""Reads the facts of the predecessor rule (`domain.predecessor`) for the preview and the run,
only those the rule asks for, in its order."""

from __future__ import annotations

from datetime import date

from di1.modules.processing.application.interfaces.repositories import (
    ChainHistory,
    DateStatusRepository,
    ProcessingChain,
)
from di1.modules.processing.domain.predecessor import (
    PredecessorFact,
    PredecessorState,
    predecessor_state,
)
from di1.modules.processing.public import ChainStatus
from di1.platform.database.unit_of_work import UnitOfWork


async def read_predecessor(
    chain: ProcessingChain,
    day_before: date,
    recorded: ChainStatus | None,
    *,
    date_statuses: DateStatusRepository,
    history: ChainHistory,
    uow: UnitOfWork,
) -> PredecessorState:
    """The state of ``day_before`` for ``chain``, given its status there (``None`` without
    one)."""
    has_earlier_status: bool | None = None
    has_chain_entries: bool | None = None
    while True:
        state = predecessor_state(
            PredecessorState(recorded.value) if recorded is not None else None,
            has_earlier_status=has_earlier_status,
            has_chain_entries=has_chain_entries,
        )
        if state is PredecessorFact.EARLIER_STATUS:
            has_earlier_status = await date_statuses.has_status_before(chain, day_before, uow=uow)
        elif state is PredecessorFact.CHAIN_ENTRIES:
            has_chain_entries = await history.has_entries_on_or_before(chain, day_before)
        else:
            return state
