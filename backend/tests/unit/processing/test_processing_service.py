"""`ProcessingService` with in-memory collaborators (spec §10.1 to §10.3, §13 item 10; OQ-5,
OQ-11, OQ-21, OQ-23, OQ-26, OQ-29, OQ-30, OQ-31). The keyset order of the history and the
Pendências' SQL are tested on PostgreSQL (``tests/integration/processing/test_requests.py``)."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest

from di1.modules.processing.domain.predecessor import PredecessorState
from di1.modules.processing.domain.runs import RequestCursor
from di1.modules.processing.public import (
    Chain,
    ChainStatus,
    ProcessingScope,
    ProcessingStatus,
)
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.paging import PageParams
from tests.unit.processing.fakes import T0, FakeUnitOfWork, Harness, date_status

ALL = ProcessingScope.ALL
CASH = ProcessingScope.CASH
POSITIONS = ProcessingScope.POSITIONS
TODAY = T0.date()  # 19/10/2026

ZERO = PredecessorState.ZERO_STATE
NOT_PROCESSED = PredecessorState.NOT_PROCESSED


@pytest.fixture
def harness() -> Harness:
    return Harness()


def _error(raised: pytest.ExceptionInfo[DomainError]) -> tuple[ErrorDetail, ...]:
    return raised.value.errors


# Preview


async def test_10_1_the_preview_covers_exactly_the_requested_range(harness: Harness) -> None:
    preview = await harness.service.preview_range(CASH, date(2026, 10, 10), date(2026, 10, 16))

    assert (preview.scope, preview.start_date, preview.end_date) == (
        CASH,
        date(2026, 10, 10),
        date(2026, 10, 16),
    )
    assert preview.total_days == 7
    assert preview.predecessor_date == date(2026, 10, 9)


DAY_BEFORE = date(2026, 10, 9)


@pytest.mark.parametrize(
    ("first_trade", "first_cash", "day_before", "scope", "expected", "asked"),
    [
        pytest.param(
            date(2026, 10, 10),
            None,
            None,
            ALL,
            (ZERO, ZERO),
            [(Chain.CASH, DAY_BEFORE), (Chain.POSITIONS, DAY_BEFORE)],
            id="a trade on the start date leaves both chains in the zero state",
        ),
        pytest.param(
            None,
            date(2026, 10, 1),
            None,
            ALL,
            (NOT_PROCESSED, ZERO),
            [(Chain.CASH, DAY_BEFORE), (Chain.POSITIONS, DAY_BEFORE)],
            id="a deposit before the range ends only the cash zero state",
        ),
        pytest.param(
            date(2026, 10, 1),
            None,
            (ChainStatus.PROCESSED_WITH_ISSUES, ChainStatus.FAILED),
            POSITIONS,
            (PredecessorState.FAILED, PredecessorState.PROCESSED_WITH_ISSUES),
            [],
            id="each chain reports its own status on the day before",
        ),
        pytest.param(
            date(2026, 10, 1),
            None,
            (ChainStatus.PROCESSED, None),
            CASH,
            (NOT_PROCESSED, PredecessorState.PROCESSED),
            [(Chain.CASH, DAY_BEFORE)],
            id="a missing cash predecessor is reported beside processed positions",
        ),
    ],
)
async def test_oq26_oq31_the_preview_reports_both_chains_on_the_day_before_the_range(
    harness: Harness,
    first_trade: date | None,
    first_cash: date | None,
    day_before: tuple[ChainStatus | None, ChainStatus | None] | None,
    scope: ProcessingScope,
    expected: tuple[PredecessorState, PredecessorState],
    asked: list[tuple[Chain, date]],
) -> None:
    """Both chains are reported whatever the scope, each read on start−1: its stored status
    there, else the Ledger is asked about start−1 (never the start date itself)."""
    harness.history.first_trade = first_trade
    harness.history.first_cash_movement = first_cash
    if day_before is not None:
        harness.date_statuses.rows[DAY_BEFORE] = date_status(DAY_BEFORE, *day_before)

    preview = await harness.service.preview_range(scope, date(2026, 10, 10), date(2026, 10, 12))

    assert (preview.cash, preview.positions) == expected
    assert harness.history.asked == asked


# Range validation, shared by the preview and the enqueue


INVALID_ORDER = ErrorDetail(
    ErrorCode.INVALID_RANGE,
    "A data inicial deve ser anterior ou igual à data final.",
    "start_date",
)
TOO_LONG = ErrorDetail(
    ErrorCode.INVALID_RANGE, "O período deve ter no máximo 3.660 dias.", "end_date"
)
FUTURE = ErrorDetail(ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "end_date")
NO_DAY_BEFORE = ErrorDetail(
    ErrorCode.INVALID_RANGE, "A data inicial deve ser posterior a 01/01/0001.", "start_date"
)
LONGEST_START = TODAY - timedelta(days=3659)  # 3,660 dates up to today, ends included


@pytest.mark.parametrize("method", ["preview_range", "enqueue_range"])
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        pytest.param(date(2026, 10, 2), date(2026, 10, 1), INVALID_ORDER, id="start after end"),
        pytest.param(
            date(2026, 10, 25),
            date(2026, 10, 18),
            INVALID_ORDER,
            id="start after end is INVALID_RANGE even in the future (OQ-29)",
        ),
        pytest.param(
            LONGEST_START - timedelta(days=1), TODAY, TOO_LONG, id="3661 dates are too many"
        ),
        pytest.param(date(2026, 10, 1), date(2026, 10, 20), FUTURE, id="ends after today"),
        pytest.param(
            date(2026, 10, 20),
            date(2026, 10, 21),
            FUTURE,
            id="only the end of an ordered future range is reported (OQ-29)",
        ),
        pytest.param(date.min, date.min, NO_DAY_BEFORE, id="01/01/0001 has no day before to read"),
    ],
)
async def test_oq14_oq29_a_bad_range_is_refused_and_nothing_is_stored(
    harness: Harness, method: str, start: date, end: date, expected: ErrorDetail
) -> None:
    """GAP-G-1, OQ-29: a processing range may not end after today (São Paulo, injected clock;
    the harness's today is 19/10/2026); a run of decades would hold the one worker for hours, so
    the span is capped at 3,660 dates; 01/01/0001 is a 422, never a crash."""
    active = await harness.enqueue()
    before = dict(harness.requests.rows)
    published = list(harness.run_messages.published)
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as raised:
        await getattr(harness.on(uow), method)(ALL, start, end)

    assert _error(raised) == (expected,)
    assert harness.requests.rows == before
    assert harness.requests.rows[active.id].status is ProcessingStatus.QUEUED
    assert uow.commits == 0
    assert harness.run_messages.published == published


@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param(LONGEST_START, TODAY, id="3660 dates"),
        pytest.param(TODAY, TODAY, id="a range ending today"),
    ],
)
async def test_oq14_a_range_at_the_limits_is_accepted(
    harness: Harness, start: date, end: date
) -> None:
    preview = await harness.service.preview_range(ALL, start, end)
    request = await harness.enqueue(start, end)

    assert preview.total_days == (end - start).days + 1
    assert request.status is ProcessingStatus.QUEUED


# Enqueue


async def test_10_1_enqueue_records_a_queued_run_of_exactly_the_range_and_commits(
    harness: Harness,
) -> None:
    uow = FakeUnitOfWork()

    request = await harness.on(uow).enqueue_range(POSITIONS, date(2026, 10, 3), date(2026, 10, 4))

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
    assert harness.run_messages.published == [(request.id, uow)]  # in the same transaction


# Cancel


async def test_10_2_a_queued_run_is_cancelled_at_once(harness: Harness) -> None:
    queued = await harness.enqueue()
    uow = FakeUnitOfWork()

    cancelled = await harness.on(uow).request_cancel(queued.id)

    assert cancelled.status is ProcessingStatus.CANCELLED
    assert cancelled.cancel_requested_at == cancelled.finished_at == cancelled.updated_at
    assert cancelled.cancel_requested_at is not None
    assert harness.requests.rows[queued.id] == cancelled
    assert harness.requests.locked == [queued.id]
    assert uow.commits == 1


async def test_10_2_a_running_run_is_flagged_for_the_worker_and_stays_running(
    harness: Harness,
) -> None:
    run = await harness.enqueue()
    harness.set_status(run.id, ProcessingStatus.RUNNING)

    flagged = await harness.service.request_cancel(run.id)

    assert flagged.status is ProcessingStatus.RUNNING  # no CANCELLING (OQ-46)
    assert flagged.cancel_requested_at == flagged.updated_at
    assert flagged.cancel_requested_at is not None
    assert flagged.finished_at is None


REQUESTED = "O cancelamento deste processamento já foi solicitado."
ENDED = "Este processamento já foi encerrado e não pode ser cancelado."


@pytest.mark.parametrize(
    ("status", "cancel_on_record", "message"),
    [
        pytest.param(ProcessingStatus.RUNNING, True, REQUESTED, id="running, cancel requested"),
        pytest.param(ProcessingStatus.COMPLETED, False, ENDED, id="completed"),
        pytest.param(
            ProcessingStatus.COMPLETED_WITH_ISSUES, False, ENDED, id="completed with issues"
        ),
        pytest.param(ProcessingStatus.CANCELLED, False, ENDED, id="cancelled"),
        pytest.param(ProcessingStatus.FAILED, False, ENDED, id="failed"),
        pytest.param(
            ProcessingStatus.CANCELLED, True, ENDED, id="cancelled with its cancel on record"
        ),
        pytest.param(
            ProcessingStatus.COMPLETED,
            True,
            ENDED,
            id="completed with a cancel that arrived during the last date (OQ-23)",
        ),
        pytest.param(ProcessingStatus.FAILED, True, ENDED, id="failed with a cancel on record"),
    ],
)
async def test_oq46_a_run_that_cannot_be_cancelled_says_why(
    harness: Harness, status: ProcessingStatus, cancel_on_record: bool, message: str
) -> None:
    """An ended run answers "encerrado", whatever cancel it has on record; "já foi solicitado"
    only for a RUNNING run whose cancel is pending."""
    run = await harness.enqueue()
    harness.set_status(run.id, ProcessingStatus.RUNNING)
    if cancel_on_record:
        await harness.service.request_cancel(run.id)
    harness.set_status(run.id, status)
    before = harness.requests.rows[run.id]
    uow = FakeUnitOfWork()

    with pytest.raises(DomainError) as raised:
        await harness.on(uow).request_cancel(run.id)

    assert _error(raised) == (ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, message),)
    assert harness.requests.rows[run.id] == before
    assert uow.commits == 0


async def test_cancelling_an_unknown_run_is_not_found(harness: Harness) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.request_cancel(uuid4())

    assert _error(raised) == (ErrorDetail(ErrorCode.NOT_FOUND, "Processamento não encontrado."),)


# History page parameters (spec §13 case 22)


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_12_a_limit_outside_1_to_200_is_refused(harness: Harness, limit: int) -> None:
    # The cursor is checked only once the size is valid: a bad cursor beside it adds nothing.
    with pytest.raises(DomainError) as raised:
        await harness.service.list_requests(PageParams(limit, "%%%"))

    assert _error(raised) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Use um limite entre 1 e 200.", "limit"),
    )


@pytest.mark.parametrize(
    "cursor",
    ["%%%", "bm90LWEta2V5c2V0", RequestCursor(T0, uuid4()).encode()[:-3], "MjAyNi0xMC0xOXx4"],
)
async def test_12_an_invalid_cursor_is_refused(harness: Harness, cursor: str) -> None:
    with pytest.raises(DomainError) as raised:
        await harness.service.list_requests(PageParams(10, cursor))

    assert _error(raised) == (
        ErrorDetail(ErrorCode.VALIDATION_ERROR, "Cursor inválido.", "cursor"),
    )
