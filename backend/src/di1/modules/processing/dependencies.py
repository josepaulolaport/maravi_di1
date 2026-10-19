"""Processing's plain factories (interfaces.md "DI composition"). The composition root wires
the other modules' collaborators in and passes the result to `presentation.http.router`; the
worker (Wave 4) uses the same factories."""

from __future__ import annotations

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerReader
from di1.modules.processing.application.services.chain_history import LedgerChainHistory
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.infrastructure.messaging.outbox_doorbell import OutboxDoorbell
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
    SqlIssueRepository,
    SqlRequestRepository,
)
from di1.modules.processing.public import DateStatusReader
from di1.shared.clock import Clock


def make_processing_service(
    *, assets: AssetReader, ledger: LedgerReader, clock: Clock
) -> ProcessingService:
    return ProcessingService(
        requests=SqlRequestRepository(),
        date_statuses=SqlDateStatusRepository(),
        issues=SqlIssueRepository(),
        chain_history=LedgerChainHistory(ledger),
        assets=assets,
        clock=clock,
        doorbell=OutboxDoorbell(),
    )


def make_date_status_reader() -> DateStatusReader:
    """Each date's chain statuses for Portfolio's read models (OQ-23, OQ-31)."""
    return SqlDateStatusRepository()
