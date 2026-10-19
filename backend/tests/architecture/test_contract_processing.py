"""Processing's frozen public contract (plan §3, W0.3b; OQ-31)."""

from __future__ import annotations

import dataclasses
import typing
from datetime import date, datetime
from uuid import uuid4

import pytest

from di1.modules.processing.public import (
    ChainStatus,
    DateStatus,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
)
from di1.shared.clock import SAO_PAULO


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
        failed_date=None,
        failed_chain=None,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = ProcessingStatus.RUNNING  # type: ignore[misc]


def test_processing_has_no_invalidator() -> None:
    # OQ-31: a write saves only the fact; nothing is marked stale.
    import di1.modules.processing.public as processing_public

    assert not hasattr(processing_public, "FinancialResultInvalidator")


def test_chain_status_matches_the_schema_check() -> None:
    assert {status.value for status in ChainStatus} == {
        "PROCESSED",
        "PROCESSED_WITH_ISSUES",
        "RUNNING",
        "FAILED",
    }


def test_a_date_status_holds_both_chains_and_their_processing_times() -> None:
    processed_at = datetime(2026, 10, 19, 9, 30, tzinfo=SAO_PAULO)
    status = DateStatus(
        date=date(2026, 10, 1),
        portfolio=ChainStatus.PROCESSED_WITH_ISSUES,
        cash=None,
        portfolio_processed_at=processed_at,
        cash_processed_at=None,
    )

    assert (status.portfolio, status.cash) == (ChainStatus.PROCESSED_WITH_ISSUES, None)
    assert (status.portfolio_processed_at, status.cash_processed_at) == (processed_at, None)


def test_a_request_records_its_first_failure() -> None:
    # OQ-40: the retry of a COMPLETED_WITH_ISSUES run is prefilled from these.
    fields = [field.name for field in dataclasses.fields(ProcessingRequest)]

    assert fields[-2:] == ["failed_date", "failed_chain"]
    hints = typing.get_type_hints(ProcessingRequest)
    assert hints["failed_date"] == date | None
    assert hints["failed_chain"] == ProcessingScope | None
