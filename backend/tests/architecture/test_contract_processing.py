"""Processing's frozen public contract (plan §3, W0.3b; OQ-31): each enum against the values of
its ``docs/schema.sql`` CHECK, and no invalidator."""

from __future__ import annotations

from di1.modules.processing.domain.issues import IssueType
from di1.modules.processing.public import (
    Chain,
    ChainStatus,
    ProcessingErrorCode,
    ProcessingScope,
    ProcessingStatus,
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


def test_processing_has_no_invalidator() -> None:
    # OQ-31: a write saves only the fact; nothing is marked stale.
    import di1.modules.processing.public as processing_public

    assert not hasattr(processing_public, "FinancialResultInvalidator")


def test_the_chain_matches_the_failed_chain_check_and_is_never_all() -> None:
    assert {chain.value for chain in Chain} == {"CASH", "POSITIONS"}


def test_processing_error_codes_are_one_enum() -> None:
    assert {code.value for code in ProcessingErrorCode} == {
        "CASH_PREDECESSOR_MISSING",
        "POSITIONS_PREDECESSOR_MISSING",
        "PROCESSING_ERROR",
        "SUPERSEDED",  # retired, still stored on old runs
        "RECOVERY_EXHAUSTED",  # retired, still stored on old runs
    }


def test_chain_status_matches_the_schema_check() -> None:
    assert {status.value for status in ChainStatus} == {
        "PROCESSED",
        "PROCESSED_WITH_ISSUES",
        "RUNNING",
        "FAILED",
    }


def test_oq31_there_are_two_issue_types() -> None:
    # ``processing.issues.issue_type`` has no CHECK of its values; this pins the two (OQ-31).
    assert {t.value for t in IssueType} == {"MISSING_REFERENCE_PRICE", "EXPIRED_OPEN_POSITION"}
