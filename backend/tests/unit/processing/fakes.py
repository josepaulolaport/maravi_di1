"""In-memory collaborators for Processing's service and HTTP unit tests."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.asset.public import Instrument
from di1.modules.processing.application.interfaces.repositories import (
    IssueRecord,
    ProcessingChain,
    status_of,
)
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.public import (
    ChainStatus,
    DateStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.platform.database.unit_of_work import UnitOfWork
from di1.shared.clock import SAO_PAULO

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=SAO_PAULO)


@dataclass
class FakeUnitOfWork:
    """Counts commits; the fakes never touch the session."""

    commits: int = 0

    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the in-memory repositories never use the session")

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class SteppingClock:
    """Each ``now`` is one second after the previous one, so FIFO order is observable."""

    current: datetime = T0

    def today(self) -> date:
        return self.current.date()

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


@dataclass
class InMemoryRequests:
    rows: dict[UUID, ProcessingRequest] = field(default_factory=dict)
    locked: list[UUID] = field(default_factory=list)

    async def add(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        self.rows[request.id] = request

    async def get(
        self, request_id: UUID, *, uow: UnitOfWork, for_update: bool = False
    ) -> ProcessingRequest | None:
        if for_update:
            self.locked.append(request_id)
        return self.rows.get(request_id)

    async def update(self, request: ProcessingRequest, *, uow: UnitOfWork) -> None:
        self.rows[request.id] = request

    async def list_newest_first(
        self, limit: int, after: tuple[datetime, UUID] | None, *, uow: UnitOfWork
    ) -> Sequence[ProcessingRequest]:
        ordered = sorted(self.rows.values(), key=lambda r: (r.created_at, r.id), reverse=True)
        if after is not None:
            ordered = [r for r in ordered if (r.created_at, r.id) < after]
        return ordered[:limit]


@dataclass
class InMemoryDateStatuses:
    rows: dict[date, DateStatus] = field(default_factory=dict)

    async def get_date_statuses(
        self, start_date: date, end_date: date, *, uow: UnitOfWork
    ) -> Mapping[date, DateStatus]:
        return {d: row for d, row in sorted(self.rows.items()) if start_date <= d <= end_date}

    async def has_status_before(
        self, chain: ProcessingChain, day: date, *, uow: UnitOfWork
    ) -> bool:
        return any(d < day and status_of(row, chain) is not None for d, row in self.rows.items())


@dataclass
class InMemoryIssues:
    rows: list[IssueRecord] = field(default_factory=list)

    async def list_current(self, *, uow: UnitOfWork) -> Sequence[IssueRecord]:
        return sorted(self.rows, key=lambda i: i.affected_date, reverse=True)


@dataclass
class FakeChainHistory:
    """The first dated entry of each chain, or none."""

    first_trade: date | None = None
    first_cash_movement: date | None = None
    asked: list[tuple[ProcessingChain, date]] = field(default_factory=list)

    async def has_entries_on_or_before(self, chain: ProcessingChain, day: date) -> bool:
        self.asked.append((chain, day))
        firsts = [self.first_trade]
        if chain is ProcessingChain.CASH:
            firsts.append(self.first_cash_movement)
        return any(first is not None and first <= day for first in firsts)


@dataclass
class FakeAssets:
    codes: dict[UUID, str] = field(default_factory=dict)

    async def get_instruments(self, instrument_ids: Collection[UUID]) -> Mapping[UUID, Instrument]:
        return {i: self._descriptor(i) for i in instrument_ids if i in self.codes}

    def _descriptor(self, instrument_id: UUID) -> Instrument:
        return Instrument(
            id=instrument_id,
            code=self.codes[instrument_id],
            product_id=UUID(int=1),
            product_code="DI1",
            instrument_type="FUTURE",
            asset_class="INTEREST_RATE_FUTURE",
            maturity_date=date(2029, 1, 2),
            face_value=Decimal("100000"),
            multiplier=Decimal("1"),
            settlement_method="CASH",
        )


@dataclass
class FakeDoorbell:
    """Counts the doorbells rung, and in which Unit of Work."""

    rung: list[object] = field(default_factory=list)

    async def ring(self, *, uow: UnitOfWork) -> None:
        self.rung.append(uow)


class Harness:
    def __init__(self) -> None:
        self.requests = InMemoryRequests()
        self.date_statuses = InMemoryDateStatuses()
        self.issues = InMemoryIssues()
        self.history = FakeChainHistory()
        self.assets = FakeAssets()
        self.clock = SteppingClock()
        self.doorbell = FakeDoorbell()
        self.service = ProcessingService(
            requests=self.requests,
            date_statuses=self.date_statuses,
            issues=self.issues,
            chain_history=self.history,
            assets=self.assets,
            clock=self.clock,
            doorbell=self.doorbell,
        )

    async def enqueue(
        self,
        start: date = date(2026, 10, 1),
        end: date = date(2026, 10, 5),
        scope: ProcessingScope = ProcessingScope.ALL,
    ) -> ProcessingRequest:
        return await self.service.enqueue_range(scope, start, end, uow=FakeUnitOfWork())

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
