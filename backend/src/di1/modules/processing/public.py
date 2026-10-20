"""Processing's public contract: the run and its statuses, and each date's chain statuses for
Portfolio's read models (interfaces.md "Processing").

Nothing outside Processing writes a status: since OQ-31 a write in Ledger or Prices saves only the
fact, and a date's results change only when the user processes it again. Changes go through the
integrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol

from di1.modules.processing.domain.date_status import Chain, ChainStatus, DateStatus
from di1.modules.processing.domain.runs import (
    ProcessingErrorCode,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)

__all__ = [
    "Chain",
    "ChainStatus",
    "DateStatus",
    "DateStatusReader",
    "ProcessingErrorCode",
    "ProcessingRequest",
    "ProcessingScope",
    "ProcessingStatus",
]


class DateStatusReader(Protocol):
    """Each date's chain statuses for Portfolio's read models (OQ-23), built on the caller's
    session, so a read sees them in the same snapshot as its own tables."""

    async def get_date_statuses(
        self, start_date: date, end_date: date
    ) -> Mapping[date, DateStatus]:
        """The statuses of [start_date, end_date]; a date with no status is absent (not
        processed). The active run's current date reads RUNNING for its live chains, though
        no date is stored RUNNING (OQ-50 item 4)."""
        ...
