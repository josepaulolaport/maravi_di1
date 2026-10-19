"""`ProcessingService` with in-memory collaborators (spec §10.1 to §10.3, §13 item 10; OQ-5,
OQ-11, OQ-21, OQ-23, OQ-26, OQ-29, OQ-30, OQ-31)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from uuid import UUID, uuid4

import pytest

from di1.modules.processing.application.interfaces.repositories import (
    IssueRecord,
    IssueType,
)
from di1.modules.processing.application.services.cursor import decode_cursor, encode_cursor
from di1.modules.processing.application.services.processing import (
    PredecessorState,
)
from di1.modules.processing.public import (
    ChainStatus,
    ProcessingScope,
    ProcessingStatus,
)
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from tests.unit.processing.fakes import T0, FakeUnitOfWork, Harness, date_status

ALL = ProcessingScope.ALL
CASH = ProcessingScope.CASH
POSITIONS = ProcessingScope.POSITIONS


@pytest.fixture
def harness() -> Harness:
    return Harness()


def _error(raised: pytest.ExceptionInfo[DomainError]) -> tuple[ErrorDetail, ...]:
    return raised.value.errors


# Preview


async def test_10_1_the_preview_covers_exactly_the_requested_range(harness: Harness) -> None:
    preview = await harness.service.preview_range(
        CASH, date(2026, 10, 10), date(2026, 10, 16), uow=FakeUnitOfWork()
    )

    assert (preview.scope, preview.start_date, preview.end_date) == (
        CASH,
        date(2026, 10, 10),
        date(2026, 10, 16),
    )
    assert preview.total_days == 7
    assert preview.predecessor_date == date(2026, 10, 9)


async def test_oq26_with_nothing_before_the_range_each_chain_is_in_its_zero_state(
    harness: Harness,
) -> None:
    harness.history.first_trade = date(2026, 10, 10)

    preview = await harness.service.preview_range(
        ALL, date(2026, 10, 10), date(2026, 10, 10), uow=FakeUnitOfWork()
    )

    assert (preview.cash, preview.positions) == (
        PredecessorState.ZERO_STATE,
        PredecessorState.ZERO_STATE,
    )


async def test_oq26_a_deposit_before_the_range_leaves_only_positions_in_the_zero_state(
    harness: Harness,
) -> None:
    harness.history.first_cash_movement = date(2026, 10, 1)

    preview = await harness.service.preview_range(
        ALL, date(2026, 10, 10), date(2026, 10, 12), uow=FakeUnitOfWork()
    )

    assert (preview.cash, preview.positions) == (
        PredecessorState.NOT_PROCESSED,
        PredecessorState.ZERO_STATE,
    )


async def test_oq31_the_preview_reports_each_chain_status_of_the_day_before(
    harness: Harness,
) -> None:
    harness.history.first_trade = date(2026, 10, 1)
    harness.date_statuses.rows[date(2026, 10, 9)] = date_status(
        date(2026, 10, 9), ChainStatus.PROCESSED_WITH_ISSUES, ChainStatus.FAILED
    )

    preview = await harness.service.preview_range(
        POSITIONS, date(2026, 10, 10), date(2026, 10, 12), uow=FakeUnitOfWork()
    )

    assert (preview.cash, preview.positions) == (
        PredecessorState.FAILED,
        PredecessorState.PROCESSED_WITH_ISSUES,
    )


async def test_oq31_a_missing_cash_predecessor_is_reported_and_enqueueing_still_allowed(
    harness: Harness,
) -> None:
    harness.history.first_trade = date(2026, 10, 1)
    harness.date_statuses.rows[date(2026, 10, 9)] = date_status(
        date(2026, 10, 9), portfolio=ChainStatus.PROCESSED
    )

    preview = await harness.service.preview_range(
        CASH, date(2026, 10, 10), date(2026, 10, 12), uow=FakeUnitOfWork()
    )
    queued = await harness.enqueue(date(2026, 10, 10), date(2026, 10, 12), CASH)

    assert preview.cash is PredecessorState.NOT_PROCESSED
    assert queued.status is ProcessingStatus.QUEUED


async def test_the_preview_refuses_a_start_after_the_end(harness: Harness) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.preview_range(
            ALL, date(2026, 10, 2), date(2026, 10, 1), uow=FakeUnitOfWork()
        )

    assert _error(raised) == (
        ErrorDetail(
            ErrorCode.INVALID_RANGE,
            "A data inicial deve ser anterior ou igual à data final.",
            "start_date",
        ),
    )


FUTURE = "A data não pode ser posterior a hoje."


async def test_oq14_g1_a_range_ending_after_today_is_refused_everywhere(
    harness: Harness,
) -> None:
    """GAP-G-1, decided by the user: a processing range may not end after today (São Paulo,
    injected clock); the harness's today is 19/10/2026."""
    active = await harness.enqueue()
    tomorrow = date(2026, 10, 20)
    calls: list[Callable[[], Awaitable[object]]] = [
        lambda: harness.service.preview_range(
            ALL, date(2026, 10, 1), tomorrow, uow=FakeUnitOfWork()
        ),
        lambda: harness.service.enqueue_range(
            ALL, date(2026, 10, 1), tomorrow, uow=FakeUnitOfWork()
        ),
    ]

    for call in calls:
        with pytest.raises(DomainError) as raised:
            await call()
        assert _error(raised) == (ErrorDetail(ErrorCode.FUTURE_DATE, FUTURE, "end_date"),)
    assert list(harness.requests.rows) == [active.id]
    assert harness.requests.rows[active.id].status is ProcessingStatus.QUEUED


async def test_oq14_g1_a_range_ending_today_is_accepted(harness: Harness) -> None:
    request = await harness.enqueue(date(2026, 10, 19), date(2026, 10, 19))

    assert request.status is ProcessingStatus.QUEUED


async def test_oq29_only_the_end_of_an_ordered_range_is_checked_against_today(
    harness: Harness,
) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.enqueue(date(2026, 10, 20), date(2026, 10, 21))

    assert _error(raised) == (ErrorDetail(ErrorCode.FUTURE_DATE, FUTURE, "end_date"),)


async def test_oq29_a_start_after_the_end_is_an_invalid_range_even_in_the_future(
    harness: Harness,
) -> None:
    """``FUTURE_DATE`` is for a range ending after today (OQ-29); this one ends on 18/10."""
    with pytest.raises(DomainError) as raised:
        await harness.enqueue(date(2026, 10, 25), date(2026, 10, 18))

    assert raised.value.code is ErrorCode.INVALID_RANGE


# Enqueue


async def test_10_1_enqueue_records_a_queued_run_of_exactly_the_range_and_commits(
    harness: Harness,
) -> None:
    uow = FakeUnitOfWork()

    request = await harness.service.enqueue_range(
        POSITIONS, date(2026, 10, 3), date(2026, 10, 4), uow=uow
    )

    assert harness.requests.rows == {request.id: request}
    assert (request.scope, request.start_date, request.end_date, request.status) == (
        POSITIONS,
        date(2026, 10, 3),
        date(2026, 10, 4),
        ProcessingStatus.QUEUED,
    )
    assert request.progress_date is None
    assert (request.dispatched_at, request.started_at, request.finished_at) == (None, None, None)
    assert (request.cancel_requested_at, request.error_code, request.error_message) == (
        None,
        None,
        None,
    )
    assert request.created_at == request.updated_at == harness.clock.current
    assert uow.commits == 1


async def test_10_2_overlapping_and_repeated_requests_are_all_queued(harness: Harness) -> None:
    first = await harness.enqueue(date(2026, 10, 1), date(2026, 10, 5))
    second = await harness.enqueue(date(2026, 10, 3), date(2026, 10, 8))
    third = await harness.enqueue(date(2026, 10, 1), date(2026, 10, 5))

    assert {r.status for r in harness.requests.rows.values()} == {ProcessingStatus.QUEUED}
    assert first.created_at < second.created_at < third.created_at  # FIFO (OQ-5)


async def test_enqueue_refuses_a_start_after_the_end_and_stores_nothing(
    harness: Harness,
) -> None:
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as raised:
        await harness.service.enqueue_range(ALL, date(2026, 10, 2), date(2026, 10, 1), uow=uow)

    assert raised.value.code is ErrorCode.INVALID_RANGE
    assert harness.requests.rows == {}
    assert uow.commits == 0


# Cancel


async def test_10_2_a_queued_run_is_cancelled_at_once(harness: Harness) -> None:
    queued = await harness.enqueue()
    uow = FakeUnitOfWork()

    cancelled = await harness.service.request_cancel(queued.id, uow=uow)

    assert cancelled.status is ProcessingStatus.CANCELLED
    assert cancelled.cancel_requested_at == cancelled.finished_at == cancelled.updated_at
    assert cancelled.cancel_requested_at is not None
    assert harness.requests.rows[queued.id] == cancelled
    assert harness.requests.locked == [queued.id]
    assert uow.commits == 1


@pytest.mark.parametrize("status", [ProcessingStatus.RUNNING, ProcessingStatus.DISPATCHED])
async def test_10_2_a_started_run_is_flagged_for_the_worker(
    harness: Harness, status: ProcessingStatus
) -> None:
    run = await harness.enqueue()
    harness.set_status(run.id, status)

    flagged = await harness.service.request_cancel(run.id, uow=FakeUnitOfWork())

    assert flagged.status is ProcessingStatus.CANCELLING
    assert flagged.cancel_requested_at == flagged.updated_at
    assert flagged.finished_at is None


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (
            ProcessingStatus.COMPLETED,
            "Este processamento já foi encerrado e não pode ser cancelado.",
        ),
        (
            ProcessingStatus.COMPLETED_WITH_ISSUES,
            "Este processamento já foi encerrado e não pode ser cancelado.",
        ),
        (
            ProcessingStatus.CANCELLED,
            "Este processamento já foi encerrado e não pode ser cancelado.",
        ),
        (ProcessingStatus.FAILED, "Este processamento já foi encerrado e não pode ser cancelado."),
        (ProcessingStatus.CANCELLING, "O cancelamento deste processamento já foi solicitado."),
    ],
)
async def test_a_finished_or_cancelling_run_is_not_cancellable(
    harness: Harness, status: ProcessingStatus, message: str
) -> None:
    run = await harness.enqueue()
    harness.set_status(run.id, status)
    before = harness.requests.rows[run.id]
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as raised:
        await harness.service.request_cancel(run.id, uow=uow)

    assert _error(raised) == (ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, message),)
    assert harness.requests.rows[run.id] == before
    assert uow.commits == 0


async def test_cancelling_an_unknown_run_is_not_found(harness: Harness) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.request_cancel(uuid4(), uow=FakeUnitOfWork())

    assert _error(raised) == (ErrorDetail(ErrorCode.NOT_FOUND, "Processamento não encontrado."),)


# Reads


async def test_12_the_history_is_newest_first_by_keyset(harness: Harness) -> None:
    runs = [await harness.enqueue() for _ in range(5)]
    newest_first = [r.id for r in reversed(runs)]

    first = await harness.service.list_requests(2, None, uow=FakeUnitOfWork())
    assert first.next_cursor is not None
    second = await harness.service.list_requests(2, first.next_cursor, uow=FakeUnitOfWork())
    assert second.next_cursor is not None
    third = await harness.service.list_requests(2, second.next_cursor, uow=FakeUnitOfWork())

    assert [r.id for r in (*first.items, *second.items, *third.items)] == newest_first
    assert third.next_cursor is None


async def test_12_an_exact_last_page_has_no_next_cursor(harness: Harness) -> None:
    for _ in range(2):
        await harness.enqueue()

    page = await harness.service.list_requests(2, None, uow=FakeUnitOfWork())

    assert (len(page.items), page.next_cursor) == (2, None)


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_12_a_limit_outside_1_to_200_is_refused(harness: Harness, limit: int) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.list_requests(limit, None, uow=FakeUnitOfWork())

    assert _error(raised) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use um limite entre 1 e 200.", "limit"),
    )


@pytest.mark.parametrize(
    "cursor", ["%%%", "bm90LWEta2V5c2V0", encode_cursor(T0, uuid4())[:-3], "MjAyNi0xMC0xOXx4"]
)
async def test_12_an_invalid_cursor_is_refused(harness: Harness, cursor: str) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.list_requests(10, cursor, uow=FakeUnitOfWork())

    assert _error(raised) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Cursor inválido.", "cursor"),
    )


def test_the_cursor_round_trips_its_keyset() -> None:
    request_id = uuid4()

    assert decode_cursor(encode_cursor(T0, request_id)) == (T0, request_id)


async def test_get_request_returns_the_run_or_not_found(harness: Harness) -> None:
    run = await harness.enqueue()

    assert await harness.service.get_request(run.id, uow=FakeUnitOfWork()) == run
    with pytest.raises(DomainError) as raised:
        await harness.service.get_request(uuid4(), uow=FakeUnitOfWork())
    assert raised.value.code is ErrorCode.NOT_FOUND


async def test_oq31_issues_carry_their_asset_code(harness: Harness) -> None:
    di1f29, di1f27, request_id = uuid4(), uuid4(), uuid4()
    harness.assets.codes[di1f29] = "DI1F29"
    harness.assets.codes[di1f27] = "DI1F27"
    missing_price = IssueRecord(
        id=uuid4(),
        request_id=request_id,
        issue_type=IssueType.MISSING_REFERENCE_PRICE,
        asset_id=di1f29,
        affected_date=date(2026, 10, 16),
        required_price_date=date(2026, 10, 16),
    )
    expired = IssueRecord(
        id=uuid4(),
        request_id=request_id,
        issue_type=IssueType.EXPIRED_OPEN_POSITION,
        asset_id=di1f27,
        affected_date=date(2026, 10, 14),
        required_price_date=None,
    )
    harness.issues.rows = [expired, missing_price]

    issues = await harness.service.get_issues(uow=FakeUnitOfWork())

    assert [(i.id, i.issue_type, i.asset_code) for i in issues] == [
        (missing_price.id, IssueType.MISSING_REFERENCE_PRICE, "DI1F29"),
        (expired.id, IssueType.EXPIRED_OPEN_POSITION, "DI1F27"),
    ]


async def test_10_3_one_row_per_obligation_with_its_earliest_affected_date(
    harness: Harness,
) -> None:
    """Spec §10.3, "deduplicar problemas repetidos para a mesma obrigação": a missing price is
    one obligation per (asset, needed date); an expired open position, one per asset."""
    di1f29, di1f27, request_id = uuid4(), uuid4(), uuid4()
    harness.assets.codes |= {di1f29: "DI1F29", di1f27: "DI1F27"}

    def issue(kind: IssueType, asset: UUID, affected: int, needed: int | None) -> IssueRecord:
        return IssueRecord(
            id=uuid4(),
            request_id=request_id,
            issue_type=kind,
            asset_id=asset,
            affected_date=date(2026, 10, affected),
            required_price_date=None if needed is None else date(2026, 10, needed),
        )

    missing = IssueType.MISSING_REFERENCE_PRICE
    expired = IssueType.EXPIRED_OPEN_POSITION
    first_valuation = issue(missing, di1f29, 16, 16)
    next_day_pnl = issue(missing, di1f29, 17, 16)
    other_day = issue(missing, di1f29, 17, 17)
    first_expired = issue(expired, di1f27, 15, None)
    harness.issues.rows = [
        issue(expired, di1f27, 17, None),
        next_day_pnl,
        other_day,
        issue(expired, di1f27, 16, None),
        first_valuation,
        first_expired,
    ]

    issues = await harness.service.get_issues(uow=FakeUnitOfWork())

    assert [i.id for i in issues] == [other_day.id, first_valuation.id, first_expired.id]


def test_oq31_there_are_two_issue_types() -> None:
    assert {t.value for t in IssueType} == {"MISSING_REFERENCE_PRICE", "EXPIRED_OPEN_POSITION"}


def test_oq31_the_predecessor_has_no_stale_state() -> None:
    assert {s.value for s in PredecessorState} == {
        "PROCESSED",
        "PROCESSED_WITH_ISSUES",
        "RUNNING",
        "FAILED",
        "NOT_PROCESSED",
        "ZERO_STATE",
    }
