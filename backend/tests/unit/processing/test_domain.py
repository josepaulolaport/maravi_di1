"""Processing's domain types: a date's status per chain and a run's current date (OQ-21, OQ-23,
OQ-31, OQ-36, OQ-40, OQ-50 item 4), the run history's cursor (spec §12), and the Pendências'
deduplication (spec §10.3, §13 case 21; OQ-37)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import pytest

from di1.modules.processing.domain.date_status import (
    Chain,
    ChainStatus,
    DateStatus,
    with_active_run,
)
from di1.modules.processing.domain.issues import IssueRecord, IssueType, deduplicate
from di1.modules.processing.domain.runs import (
    ProcessingErrorCode,
    ProcessingRequest,
    ProcessingScope,
    ProcessingStatus,
    RequestCursor,
)
from di1.shared.clock import SAO_PAULO

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=SAO_PAULO)
D1, D2, D3 = date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)


def run(
    scope: ProcessingScope = ProcessingScope.ALL,
    status: ProcessingStatus = ProcessingStatus.RUNNING,
    progress_date: date | None = None,
    failed_chain: Chain | None = None,
) -> ProcessingRequest:
    return ProcessingRequest(
        id=uuid4(),
        scope=scope,
        start_date=D1,
        end_date=D3,
        status=status,
        created_at=T0,
        dispatched_at=None,
        started_at=T0,
        finished_at=None,
        cancel_requested_at=None,
        progress_date=progress_date,
        error_code=None,
        error_message=None,
        updated_at=T0,
        failed_date=None if failed_chain is None else D1,
        failed_chain=failed_chain,
    )


@pytest.mark.parametrize(
    ("status", "processed"),
    [
        (ChainStatus.PROCESSED, True),
        (ChainStatus.PROCESSED_WITH_ISSUES, True),
        (ChainStatus.FAILED, False),
        (ChainStatus.RUNNING, False),
    ],
)
def test_only_processed_statuses_count_as_processed(status: ChainStatus, processed: bool) -> None:
    assert status.is_processed is processed


def test_a_date_settles_one_chain_and_keeps_the_others_time() -> None:
    before = DateStatus(D1, ChainStatus.PROCESSED, ChainStatus.PROCESSED, T0, T0)
    later = datetime(2026, 10, 20, 9, 0, tzinfo=SAO_PAULO)

    processed = before.settled(Chain.CASH, ChainStatus.PROCESSED, later)
    failed = before.settled(Chain.POSITIONS, ChainStatus.FAILED, None)

    assert (processed.cash, processed.cash_processed_at, processed.portfolio_processed_at) == (
        ChainStatus.PROCESSED,
        later,
        T0,
    )
    assert (failed.portfolio, failed.portfolio_processed_at) == (ChainStatus.FAILED, T0)
    assert failed.status(Chain.POSITIONS) is ChainStatus.FAILED


def test_all_runs_positions_first_and_a_single_chain_alone() -> None:
    assert ProcessingScope.ALL.chains == (Chain.POSITIONS, Chain.CASH)
    assert ProcessingScope.CASH.chains == (Chain.CASH,)
    assert ProcessingScope.POSITIONS.chains == (Chain.POSITIONS,)


def test_oq50_a_running_run_is_on_the_day_after_its_progress() -> None:
    assert run().current_date == D1
    assert run(progress_date=D1).current_date == D2
    assert run(progress_date=D3).current_date is None  # past its end: only recording it
    assert run(status=ProcessingStatus.QUEUED).current_date is None
    assert run(status=ProcessingStatus.COMPLETED, progress_date=D1).current_date is None


def test_oq36_on_all_the_chain_that_failed_first_is_no_longer_live() -> None:
    assert run().live_chains == (Chain.POSITIONS, Chain.CASH)
    assert run(failed_chain=Chain.CASH).live_chains == (Chain.POSITIONS,)
    assert run(ProcessingScope.CASH).live_chains == (Chain.CASH,)


def test_oq50_with_active_run_shows_processando_only_on_its_current_date() -> None:
    stored = {D1: DateStatus(D1, cash=ChainStatus.PROCESSED, cash_processed_at=T0)}

    shown = with_active_run(
        stored, current_date=D1, live_chains=(Chain.CASH,), start_date=D1, end_date=D3
    )
    outside = with_active_run(
        stored, current_date=D1, live_chains=(Chain.CASH,), start_date=D2, end_date=D3
    )

    assert shown == {D1: DateStatus(D1, cash=ChainStatus.RUNNING, cash_processed_at=T0)}
    assert outside == stored
    assert with_active_run(
        stored, current_date=None, live_chains=(), start_date=D1, end_date=D3
    ) == (stored)


def test_a_predecessor_error_code_names_its_chain() -> None:
    assert (
        ProcessingErrorCode.predecessor_missing(Chain.CASH)
        is ProcessingErrorCode.CASH_PREDECESSOR_MISSING
    )
    assert (
        ProcessingErrorCode.predecessor_missing(Chain.POSITIONS)
        is ProcessingErrorCode.POSITIONS_PREDECESSOR_MISSING
    )


def test_processing_error_codes_are_one_enum() -> None:
    # Retired codes stay, since old runs still store them:
    # SUPERSEDED (OQ-30) and RECOVERY_EXHAUSTED (OQ-45).
    assert {code.value for code in ProcessingErrorCode} == {
        "CASH_PREDECESSOR_MISSING",
        "POSITIONS_PREDECESSOR_MISSING",
        "PROCESSING_ERROR",
        "SUPERSEDED",
        "RECOVERY_EXHAUSTED",
    }


def test_the_history_cursor_round_trips_and_refuses_anything_else() -> None:
    cursor = RequestCursor(T0, uuid4())

    assert RequestCursor.decode(cursor.encode()) == cursor
    assert (
        RequestCursor.decode(replace(cursor, created_at=T0.replace(tzinfo=None)).encode()) is None
    )
    assert RequestCursor.decode("%%%") is None


def test_10_3_one_pendencia_per_obligation_with_its_earliest_affected_date() -> None:
    """Spec §10.3, "deduplicar problemas repetidos para a mesma obrigação": a missing price is
    one obligation per (asset, needed date); an expired open position, one per asset. Newest
    affected date first."""
    di1f29, di1f27 = UUID(int=29), UUID(int=27)

    def issue(kind: IssueType, asset: UUID, affected: int, needed: int | None) -> IssueRecord:
        return IssueRecord(
            id=uuid4(),
            issue_type=kind,
            asset_id=asset,
            affected_date=date(2026, 10, affected),
            required_price_date=None if needed is None else date(2026, 10, needed),
        )

    missing = IssueType.MISSING_REFERENCE_PRICE
    expired = IssueType.EXPIRED_OPEN_POSITION
    first_valuation = issue(missing, di1f29, 16, 16)
    next_day_pnl = issue(missing, di1f29, 17, 16)  # the same price, needed again on 17/10
    other_day = issue(missing, di1f29, 17, 17)
    first_expired = issue(expired, di1f27, 15, None)

    kept = deduplicate(
        [
            issue(expired, di1f27, 17, None),
            next_day_pnl,
            other_day,
            issue(expired, di1f27, 16, None),
            first_valuation,
            first_expired,
        ]
    )

    assert kept == [other_day, first_valuation, first_expired]
