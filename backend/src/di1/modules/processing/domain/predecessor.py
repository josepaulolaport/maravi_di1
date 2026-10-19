"""The predecessor rule, per day (interfaces.md "Predecessor rule, per day"; OQ-26 item 8,
OQ-31 item 4, OQ-37 item 4, OQ-40 item 5).

For one chain and a date D, the state of D−1 decides whether D may run. The rule is the only
copy shared by the preview (which reports the state) and the run (which fails D unless it
allows a run). It is pure: the facts it needs come in as arguments, and while one is missing
it names the next one to read, so a caller reads only what the rule needs, in the rule's
order, and the Ledger is asked only when the chain has no status before D (OQ-37 item 4).
"""

from __future__ import annotations

from enum import StrEnum


class PredecessorState(StrEnum):
    """The day before a date, for one chain: its recorded status in ``date_status``, or, without
    one, NOT_PROCESSED or ZERO_STATE (the chain has nothing on or before it). There is no
    stale state (OQ-31)."""

    PROCESSED = "PROCESSED"
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    NOT_PROCESSED = "NOT_PROCESSED"
    ZERO_STATE = "ZERO_STATE"


class PredecessorFact(StrEnum):
    """A fact the rule still needs, in the order it needs them."""

    EARLIER_STATUS = "EARLIER_STATUS"
    """Whether the chain has a status on any date before D−1."""
    CHAIN_ENTRIES = "CHAIN_ENTRIES"
    """Whether the Ledger has an entry of the chain's type on or before D−1 (positions: a
    trade; cash: an entry of either type; OQ-32)."""


RECORDED = frozenset(
    {
        PredecessorState.PROCESSED,
        PredecessorState.PROCESSED_WITH_ISSUES,
        PredecessorState.RUNNING,
        PredecessorState.FAILED,
    }
)
"""The states a ``date_status`` row can hold for a chain."""

RUNNABLE = frozenset(
    {
        PredecessorState.PROCESSED,
        PredecessorState.PROCESSED_WITH_ISSUES,
        PredecessorState.ZERO_STATE,
    }
)


def predecessor_state(
    recorded: PredecessorState | None,
    *,
    has_earlier_status: bool | None = None,
    has_chain_entries: bool | None = None,
) -> PredecessorState | PredecessorFact:
    """The state of D−1 for one chain, or the next fact to read when it is not yet decided.

    1. A status recorded on D−1 is the state, whatever it is (a FAILED or RUNNING D−1 fails D).
    2. Otherwise, a status on an earlier date makes D−1 a gap: NOT_PROCESSED.
    3. Otherwise, an entry of the chain on or before D−1 means it was never processed:
       NOT_PROCESSED; with none, the chain is in its ZERO_STATE.
    """
    if recorded is not None:
        if recorded not in RECORDED:
            raise ValueError(f"{recorded} is not a recorded status")
        return recorded
    if has_earlier_status is None:
        return PredecessorFact.EARLIER_STATUS
    if has_earlier_status:
        return PredecessorState.NOT_PROCESSED
    if has_chain_entries is None:
        return PredecessorFact.CHAIN_ENTRIES
    return PredecessorState.NOT_PROCESSED if has_chain_entries else PredecessorState.ZERO_STATE


def allows_run(state: PredecessorState) -> bool:
    """D may run only from a processed D−1 or from the chain's zero state; otherwise it fails
    with the chain's ``*_PREDECESSOR_MISSING`` (OQ-31)."""
    return state in RUNNABLE
