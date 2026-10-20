"""The state of a date's day before, for one chain (interfaces.md "Predecessor rule, per day";
OQ-26 item 8, OQ-31 item 4, OQ-37 item 4, OQ-40 item 5). The rule that decides it is
`application.services.predecessor.read_predecessor`, shared by the preview and the run."""

from __future__ import annotations

from enum import StrEnum


class PredecessorState(StrEnum):
    """The day before, for one chain: its stored status in ``date_status`` or, without one,
    NOT_PROCESSED or ZERO_STATE (the chain has nothing on or before it). There is no stale state
    (OQ-31). RUNNING stays for the API's enum; since OQ-50 item 4 no date is stored RUNNING."""

    PROCESSED = "PROCESSED"
    PROCESSED_WITH_ISSUES = "PROCESSED_WITH_ISSUES"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    NOT_PROCESSED = "NOT_PROCESSED"
    ZERO_STATE = "ZERO_STATE"

    @property
    def allows_run(self) -> bool:
        """D may run only from a processed D−1 or from the chain's zero state; otherwise it fails
        with the chain's ``*_PREDECESSOR_MISSING`` (OQ-31)."""
        return self in (
            PredecessorState.PROCESSED,
            PredecessorState.PROCESSED_WITH_ISSUES,
            PredecessorState.ZERO_STATE,
        )
