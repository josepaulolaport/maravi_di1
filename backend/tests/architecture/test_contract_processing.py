"""Processing's frozen public contract and the invalidator fake (plan §3, W0.3b)."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from di1.modules.processing.public import (
    ChainStatus,
    FinancialResultInvalidator,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.shared.clock import SAO_PAULO
from tests.fakes.processing import (
    CashMovementsChanged,
    PricesChanged,
    RecordingInvalidator,
    TradesChanged,
)


def test_processing_status_has_the_eight_schema_statuses() -> None:
    assert {status.value for status in ProcessingStatus} == {
        "QUEUED",
        "DISPATCHED",
        "RUNNING",
        "CANCELLING",
        "COMPLETED",
        "COMPLETED_WITH_ISSUES",
        "CANCELLED",
        "FAILED",
    }


def test_processing_scope_matches_the_schema_check() -> None:
    assert {scope.value for scope in ProcessingScope} == {"CASH", "POSITIONS", "ALL"}


def test_a_request_is_frozen_and_covers_exactly_its_range() -> None:
    request = ProcessingRequest(
        id=uuid4(),
        scope=ProcessingScope.CASH,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 16),
        status=ProcessingStatus.QUEUED,
        created_at=datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO),
        dispatched_at=None,
        started_at=None,
        finished_at=None,
        cancel_requested_at=None,
        progress_date=None,
        error_code=None,
        error_message=None,
        updated_at=datetime(2026, 10, 16, 18, 0, tzinfo=SAO_PAULO),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = ProcessingStatus.RUNNING  # type: ignore[misc]


class _UnusedUnitOfWork:
    @property
    def session(self) -> AsyncSession:
        raise AssertionError("the invalidator fake never touches the session")

    async def commit(self) -> None:
        raise AssertionError("the invalidator never commits")


async def test_the_fake_invalidator_records_calls_with_their_unit_of_work() -> None:
    invalidator: FinancialResultInvalidator = RecordingInvalidator()
    uow = _UnusedUnitOfWork()
    asset_id = uuid4()

    await invalidator.trades_changed(date(2026, 10, 1), uow=uow)
    await invalidator.cash_movements_changed(date(2026, 10, 3), uow=uow)
    await invalidator.prices_changed(asset_id, date(2026, 10, 2), uow=uow)

    assert isinstance(invalidator, RecordingInvalidator)
    assert invalidator.calls == [
        TradesChanged(date(2026, 10, 1), uow),
        CashMovementsChanged(date(2026, 10, 3), uow),
        PricesChanged(asset_id, date(2026, 10, 2), uow),
    ]


def test_chain_status_matches_the_schema_check() -> None:
    assert {status.value for status in ChainStatus} == {
        "FRESH",
        "FRESH_WITH_ISSUES",
        "STALE",
        "RUNNING",
        "FAILED",
    }
