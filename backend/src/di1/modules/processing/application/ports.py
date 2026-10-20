"""What Processing's services need from persistence, the Ledger and the broker (implemented in
``infrastructure/``). Each port is built on one Unit of Work's session and never commits: the
service, or the run's step, owns the transaction (interfaces.md "Transaction boundaries")."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from di1.modules.asset.public import AssetReader
from di1.modules.ledger.public import LedgerReader
from di1.modules.portfolio.public import PortfolioReader, PortfolioResultsWriter
from di1.modules.prices.public import PriceReader
from di1.modules.processing.domain.date_status import Chain, DateStatus
from di1.modules.processing.domain.issues import IssueRecord
from di1.modules.processing.domain.runs import ProcessingRequest

RUN_MESSAGE_TYPE = "processing.run"
"""The run message's type; also the worker's queue name and its routing key (OQ-50 item 2)."""


class RequestRepository(Protocol):
    """``processing.requests``."""

    async def add(self, request: ProcessingRequest) -> None: ...

    async def get(self, request_id: UUID, *, for_update: bool = False) -> ProcessingRequest | None:
        """The run, row-locked when ``for_update``."""
        ...

    async def save(self, request: ProcessingRequest) -> None:
        """Stores every mutable column: status, timestamps, progress and failure."""
        ...

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None
    ) -> Sequence[ProcessingRequest]:
        """At most ``limit`` runs by ``(created_at, id)`` descending, strictly after ``after``."""
        ...

    async def get_running(self) -> ProcessingRequest | None:
        """The run the worker is processing, if any (a plain read; one at a time, OQ-45)."""
        ...

    async def lock_queue(self) -> None:
        """Takes the queue's transaction-scoped lock, held until the Unit of Work ends: two takes
        are serialized, so "nothing RUNNING, then lock the oldest QUEUED" is one atomic step."""
        ...

    async def lock_running(self) -> Sequence[ProcessingRequest]:
        """The RUNNING runs, oldest first, row-locked: the one the worker is processing, or at its
        start the one it was (OQ-45)."""
        ...

    async def lock_oldest_queued(self) -> ProcessingRequest | None:
        """The oldest QUEUED run by ``(created_at, id)``, row-locked (OQ-5 item 4, OQ-46)."""
        ...

    async def has_queued(self) -> bool: ...


class DateStatusRepository(Protocol):
    """``processing.date_status`` as stored: no derived RUNNING (OQ-50 item 4)."""

    async def get_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        """The rows of [start_date, end_date]; a date with no row is absent."""
        ...

    async def lock_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        """The same rows, row-locked in ascending date order."""
        ...

    async def has_status_before(self, chain: Chain, day: date) -> bool:
        """Whether ``chain`` has a status on any date before ``day``."""
        ...

    async def save(self, status: DateStatus) -> None:
        """Upserts the date's statuses and processing times."""
        ...


class IssueRepository(Protocol):
    """``processing.issues``: a date's Pendências, replaced whenever the date is processed (OQ-26
    item 5), so every stored one is current."""

    async def list_current(self) -> Sequence[IssueRecord]: ...

    async def replace_for_date(
        self, request_id: UUID, day: date, issues: Sequence[IssueRecord]
    ) -> None: ...


class ChainHistory(Protocol):
    """The zero state of a chain (OQ-22, OQ-26 item 3), read from the Ledger."""

    async def has_entries_on_or_before(self, chain: Chain, day: date) -> bool:
        """Positions: a trade dated on or before ``day``; cash: an entry of either type
        (OQ-32: every ledger row is live)."""
        ...


class RunMessages(Protocol):
    """The run message: one per queued request, written in the request's transaction and
    published by the relay once it commits. On any run message the worker takes the oldest
    QUEUED request, so the message's ``request_id`` serves the logs only, and its periodic sweep
    does the same, so a lost message only delays a run (OQ-50 item 2)."""

    async def publish(self, request_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class ChainPorts:
    """What a date of each chain reads from the other modules and writes to Portfolio."""

    ledger: LedgerReader
    prices: PriceReader
    assets: AssetReader
    portfolio: PortfolioReader
    writer: PortfolioResultsWriter


@dataclass(frozen=True, slots=True)
class RunPorts:
    """Everything one step of a run reads and writes, all on that step's Unit of Work."""

    requests: RequestRepository
    date_statuses: DateStatusRepository
    issues: IssueRepository
    history: ChainHistory
    chains: ChainPorts
    savepoint: Callable[[], AbstractAsyncContextManager[object]]
    """A SAVEPOINT in the step's transaction: leaving it through an exception rolls back to it,
    and the transaction stays usable (OQ-40 item 1)."""
