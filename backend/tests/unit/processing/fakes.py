"""In-memory collaborators for Processing's service and HTTP unit tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from uuid import UUID

from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.domain.issues import IssueRecord
from di1.modules.processing.public import (
    Chain,
    ChainStatus,
    DateStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from tests.support.fakes import FakeAssetReader, FakeChainHistory, FakeUnitOfWork, stepping_clock


@dataclass
class InMemoryRequests:
    rows: dict[UUID, ProcessingRequest] = field(default_factory=dict)
    locked: list[UUID] = field(default_factory=list)

    async def add(self, request: ProcessingRequest) -> None:
        self.rows[request.id] = request

    async def get(self, request_id: UUID, for_update: bool = False) -> ProcessingRequest | None:
        if for_update:
            self.locked.append(request_id)
        return self.rows.get(request_id)

    async def lock_queue(self) -> None:
        pass

    async def lock_running(self) -> Sequence[ProcessingRequest]:
        running = [r for r in self.rows.values() if r.status is ProcessingStatus.RUNNING]
        return sorted(running, key=lambda r: (r.created_at, r.id))

    async def lock_oldest_queued(self) -> ProcessingRequest | None:
        queued = [r for r in self.rows.values() if r.status is ProcessingStatus.QUEUED]
        return min(queued, key=lambda r: (r.created_at, r.id), default=None)

    async def has_queued(self) -> bool:
        return await self.lock_oldest_queued() is not None

    async def get_running(self) -> ProcessingRequest | None:
        running = [r for r in self.rows.values() if r.status is ProcessingStatus.RUNNING]
        return min(running, key=lambda r: (r.created_at, r.id), default=None)

    async def save(self, request: ProcessingRequest) -> None:
        self.rows[request.id] = request

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None
    ) -> Sequence[ProcessingRequest]:
        """The first page only: the keyset is SQL, tested on PostgreSQL (``test_requests.py``)."""
        if after is not None:
            raise AssertionError("the keyset is tested on PostgreSQL, not on this fake")
        ordered = sorted(self.rows.values(), key=lambda r: (r.created_at, r.id), reverse=True)
        return ordered[:limit]


@dataclass
class InMemoryDateStatuses:
    rows: dict[date, DateStatus] = field(default_factory=dict)

    async def get_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        return {d: row for d, row in sorted(self.rows.items()) if start_date <= d <= end_date}

    async def lock_range(self, start_date: date, end_date: date) -> Mapping[date, DateStatus]:
        return await self.get_range(start_date, end_date)

    async def save(self, status: DateStatus) -> None:
        self.rows[status.date] = status

    async def has_status_before(self, chain: Chain, day: date) -> bool:
        return any(d < day and row.status(chain) is not None for d, row in self.rows.items())


@dataclass
class InMemoryIssues:
    rows: list[IssueRecord] = field(default_factory=list)

    async def list_current(self) -> Sequence[IssueRecord]:
        return sorted(self.rows, key=lambda i: i.affected_date, reverse=True)

    async def replace_for_date(
        self, request_id: UUID, day: date, issues: Sequence[IssueRecord]
    ) -> None:
        self.rows = [i for i in self.rows if i.affected_date != day]
        self.rows += [replace(i, request_id=request_id) for i in issues]


@dataclass
class FakeRunMessages:
    """Records the run messages published: ``(request_id, uow)``, ``uow`` the Unit of Work the
    service was built on."""

    published: list[tuple[UUID, object]] = field(default_factory=list)

    def on(self, uow: FakeUnitOfWork) -> BoundRunMessages:
        return BoundRunMessages(self, uow)


@dataclass
class BoundRunMessages:
    messages: FakeRunMessages
    uow: FakeUnitOfWork

    async def publish(self, request_id: UUID) -> None:
        self.messages.published.append((request_id, self.uow))


class Harness:
    def __init__(self) -> None:
        self.requests = InMemoryRequests()
        self.date_statuses = InMemoryDateStatuses()
        self.issues = InMemoryIssues()
        self.history = FakeChainHistory()
        self.assets = FakeAssetReader()
        self.clock = stepping_clock()
        self.run_messages = FakeRunMessages()

    def on(self, uow: FakeUnitOfWork) -> ProcessingService:
        """The service on ``uow``, as the composition builds it per request."""
        return ProcessingService(
            uow,
            requests=self.requests,
            date_statuses=self.date_statuses,
            issues=self.issues,
            chain_history=self.history,
            run_messages=self.run_messages.on(uow),
            assets=self.assets,
            clock=self.clock,
        )

    @property
    def service(self) -> ProcessingService:
        """The service on a fresh Unit of Work."""
        return self.on(FakeUnitOfWork())

    async def enqueue(
        self,
        start: date = date(2026, 10, 1),
        end: date = date(2026, 10, 5),
        scope: ProcessingScope = ProcessingScope.ALL,
    ) -> ProcessingRequest:
        return await self.service.enqueue_range(scope, start, end)

    def set_status(self, request_id: UUID, status: ProcessingStatus) -> None:
        self.requests.rows[request_id] = replace(self.requests.rows[request_id], status=status)


def date_status(
    day: date,
    portfolio: ChainStatus | None = None,
    cash: ChainStatus | None = None,
    *,
    processed_at: datetime | None = None,
) -> DateStatus:
    """A ``date_status`` row; each chain with a status gets ``processed_at``."""
    return DateStatus(
        date=day,
        portfolio=portfolio,
        cash=cash,
        portfolio_processed_at=processed_at if portfolio is not None else None,
        cash_processed_at=processed_at if cash is not None else None,
    )
