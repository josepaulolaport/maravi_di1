"""The worker on PostgreSQL: the doorbell and the FIFO drain (OQ-46), one transaction per date,
recovery at worker start (OQ-45), and plan §7's adversarial sequences (interfaces.md
"Processing", "Transaction boundaries" 4 to 7; OQ-5, OQ-23, OQ-26, OQ-31, OQ-36 to OQ-40)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.ledger.public import EntryType
from di1.modules.portfolio.public import CashBalance
from di1.modules.prices.public import PriceSource
from di1.modules.processing.domain.predecessor import PredecessorState, allows_run
from tests.integration.processing.support import seed_instrument, seed_statuses
from tests.integration.processing.worker_support import Worker
from tests.unit.processing.run_fakes import cash_movement, trade

D1, D2, D3 = date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)
D0 = date(2026, 10, 5)


@pytest.fixture
async def worker(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Worker]:
    w = Worker(engine, session_factory)
    await w.setup()
    yield w


async def priced_asset(w: Worker, *days: date, pu: str = "95000.0000000000") -> UUID:
    asset_id = await seed_instrument(w.engine, "DI1F29")
    w.world.instruments.maturities[asset_id] = date(2029, 1, 2)
    for day in days:
        w.world.prices.set(asset_id, day, pu, PriceSource.B3)
    return asset_id


# --- the doorbell and the queue (OQ-46) --------------------------------------------------


async def test_requests_run_oldest_first_by_created_at(worker: Worker) -> None:
    later = await worker.enqueue("CASH", D3, D3)
    worker.clock.advance(-10)  # created before the first, inserted after it
    earliest = await worker.enqueue("CASH", D1, D1)
    worker.clock.advance(20)
    last = await worker.enqueue("CASH", D2, D2)

    taken: list[UUID] = []
    while (request_id := await worker.take_next()) is not None:
        taken.append(request_id)
        await worker.processor.run(request_id)

    assert taken == [earliest, later, last]  # by (created_at, id), not by insertion


async def test_a_doorbell_with_nothing_queued_is_a_no_op(worker: Worker) -> None:
    await worker.ring()

    assert await worker.statuses() == {}
    assert await worker.writes() == []


async def test_a_duplicate_doorbell_is_a_no_op(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.ring()
    after_first = (
        await worker.run_row(request_id),
        await worker.status_rows(),
        await worker.writes(),
    )

    await worker.ring()  # the same message again, or a late one

    assert (
        await worker.run_row(request_id),
        await worker.status_rows(),
        await worker.writes(),
    ) == after_first


async def test_a_lost_doorbell_is_covered_by_the_next_requests_doorbell(worker: Worker) -> None:
    first = await worker.enqueue("CASH", D1, D1)  # its doorbell never arrives
    second = await worker.enqueue("CASH", D2, D2)

    await worker.ring()  # the second request's doorbell

    assert (await worker.run_row(first))["status"] == "COMPLETED"
    assert (await worker.run_row(second))["status"] == "COMPLETED"


async def test_a_lost_doorbell_is_covered_by_a_restart(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)  # its doorbell never arrives

    await worker.restart()

    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


async def test_nothing_is_taken_while_a_run_is_running(worker: Worker) -> None:
    first = await worker.enqueue("CASH", D1, D1)
    second = await worker.enqueue("CASH", D2, D2)
    assert await worker.take_next() == first

    assert await worker.take_next() is None  # one run at a time
    await worker.ring()
    assert (await worker.run_row(second))["status"] == "QUEUED"


async def test_a_queued_request_cancelled_before_pickup_never_runs(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.cancel(request_id)

    await worker.ring()

    assert (await worker.run_row(request_id))["status"] == "CANCELLED"
    assert await worker.statuses() == {}
    assert await worker.writes() == []


async def end_completed(worker: Worker) -> UUID:
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.ring()
    return request_id


async def end_completed_with_issues(worker: Worker) -> UUID:
    asset = await priced_asset(worker)  # no price: a Pendência
    worker.world.ledger.trades.append(trade(asset, D1, 1, "95000.0000000000"))
    request_id = await worker.enqueue("POSITIONS", D1, D1)
    await worker.ring()
    return request_id


async def end_failed(worker: Worker) -> UUID:
    await seed_statuses(worker.engine, {D0: (None, "FAILED")})
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.ring()
    return request_id


async def end_cancelled_between_dates(worker: Worker) -> UUID:
    request_id = await worker.enqueue("CASH", D1, D2)
    assert await worker.take_next() == request_id
    await worker.cancel(request_id)
    await worker.processor.run(request_id)
    return request_id


async def end_cancelled_at_the_worker_start(worker: Worker) -> UUID:
    request_id = await worker.enqueue("CASH", D1, D2)
    assert await worker.take_next() == request_id
    await worker.cancel(request_id)
    await worker.restart()
    return request_id


@pytest.mark.parametrize(
    ("end", "status"),
    [
        (end_completed, "COMPLETED"),
        (end_completed_with_issues, "COMPLETED_WITH_ISSUES"),
        (end_failed, "FAILED"),
        (end_cancelled_between_dates, "CANCELLED"),
        (end_cancelled_at_the_worker_start, "CANCELLED"),
    ],
)
async def test_after_every_kind_of_end_the_next_doorbell_runs_the_next_request(
    worker: Worker, end: Callable[[Worker], Awaitable[UUID]], status: str
) -> None:
    ended = await end(worker)
    assert (await worker.run_row(ended))["status"] == status
    queued = await worker.enqueue("CASH", D3, D3)

    await worker.ring()

    assert (await worker.run_row(queued))["status"] in {"COMPLETED", "FAILED"}
    assert (await worker.run_row(queued))["started_at"] is not None


# --- a run end to end -----------------------------------------------------------------------


async def test_a_cash_run_from_the_zero_state_processes_every_date(worker: Worker) -> None:
    worker.world.ledger.movements.append(cash_movement(D1, "1000.00"))
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.ring()

    assert await worker.statuses() == {
        D1: (None, "PROCESSED"),
        D2: (None, "PROCESSED"),
        D3: (None, "PROCESSED"),
    }
    rows = await worker.status_rows()
    assert rows[D1]["cash_processed_at"] == worker.clock.now()
    assert rows[D1]["cash_previous"] is None
    run = await worker.run_row(request_id)
    assert run["status"] == "COMPLETED"
    assert run["progress_date"] == D3
    assert run["finished_at"] is not None
    assert run["error_code"] is None
    # A CASH run: AUM follows the positions status of each date, here not processed (OQ-38).
    assert await worker.writes() == [(D1, "CASH", False), (D2, "CASH", False), (D3, "CASH", False)]


async def test_a_cash_run_counts_positions_processed_by_another_run(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D1: ("PROCESSED", None)})
    await worker.enqueue("CASH", D1, D1)

    await worker.ring()

    assert await worker.writes() == [(D1, "CASH", True)]


async def test_an_all_run_writes_positions_first_then_cash_with_its_outcome(
    worker: Worker,
) -> None:
    asset = await priced_asset(worker, D1, D2)
    worker.world.ledger.trades.append(trade(asset, D1, 10, "95000.0000000000"))
    request_id = await worker.enqueue("ALL", D1, D2)

    await worker.ring()

    assert await worker.statuses() == {
        D1: ("PROCESSED", "PROCESSED"),
        D2: ("PROCESSED", "PROCESSED"),
    }
    # OQ-38: positions passes False, cash the positions outcome.
    assert await worker.writes() == [
        (D1, "CASH", True),
        (D1, "POSITIONS", False),
        (D2, "CASH", True),
        (D2, "POSITIONS", False),
    ]
    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


async def test_a_missing_saturday_price_is_an_issue_not_a_failure(worker: Worker) -> None:
    saturday, sunday = date(2026, 10, 10), date(2026, 10, 11)
    asset = await priced_asset(worker, saturday)  # no Sunday price, no carry-forward
    worker.world.ledger.trades.append(trade(asset, saturday, 5, "95000.0000000000"))
    request_id = await worker.enqueue("POSITIONS", saturday, sunday)

    await worker.ring()

    assert await worker.statuses() == {
        saturday: ("PROCESSED", None),
        sunday: ("PROCESSED_WITH_ISSUES", None),
    }
    assert await worker.issues() == [("MISSING_REFERENCE_PRICE", sunday, sunday)]
    run = await worker.run_row(request_id)
    assert run["status"] == "COMPLETED_WITH_ISSUES"
    assert run["error_code"] is None
    assert run["failed_date"] is None


async def test_reprocessing_a_date_replaces_its_issues(worker: Worker) -> None:
    asset = await priced_asset(worker)
    worker.world.ledger.trades.append(trade(asset, D1, 5, "95000.0000000000"))
    await worker.enqueue("POSITIONS", D1, D1)
    await worker.ring()
    assert await worker.issues() == [("MISSING_REFERENCE_PRICE", D1, D1)]

    worker.world.prices.set(asset, D1, "95000.0000000000")
    second = await worker.enqueue("POSITIONS", D1, D1)
    await worker.ring()

    assert await worker.issues() == []
    assert await worker.statuses() == {D1: ("PROCESSED", None)}
    assert (await worker.run_row(second))["status"] == "COMPLETED"


# --- predecessor rule (OQ-31, OQ-37 item 4, OQ-40 item 5) -----------------------------------


async def test_a_gap_before_the_first_date_fails_it_without_asking_the_ledger(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {date(2026, 10, 1): (None, "PROCESSED")})
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.ring()

    statuses = await worker.statuses()
    assert statuses[D1] == (None, "FAILED")
    assert D2 not in statuses and D3 not in statuses  # later dates untouched
    assert worker.world.ledger.asked == []
    run = await worker.run_row(request_id)
    assert run["status"] == "FAILED"
    assert run["error_code"] == "CASH_PREDECESSOR_MISSING"
    assert run["error_message"] == "Dia anterior não processado"
    assert run["failed_date"] == D1
    assert run["failed_chain"] == "CASH"
    assert run["progress_date"] is None
    assert await worker.writes() == []


@pytest.mark.parametrize("previous", ["FAILED", "RUNNING"])
async def test_a_failed_or_running_day_before_fails_the_date(worker: Worker, previous: str) -> None:
    await seed_statuses(worker.engine, {D0: (None, previous)})
    request_id = await worker.enqueue("CASH", D1, D1)

    await worker.ring()

    assert (await worker.statuses())[D1] == (None, "FAILED")
    assert worker.world.ledger.asked == []
    assert (await worker.run_row(request_id))["error_code"] == "CASH_PREDECESSOR_MISSING"


async def test_entries_before_an_unprocessed_first_date_fail_it(worker: Worker) -> None:
    asset = await priced_asset(worker)
    worker.world.ledger.trades.append(trade(asset, D0, 1, "95000.0000000000"))
    request_id = await worker.enqueue("POSITIONS", D1, D2)

    await worker.ring()

    assert worker.world.ledger.asked == [(D0, EntryType.TRADE)]
    assert await worker.statuses() == {D1: ("FAILED", None)}
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_chain"]) == (
        "FAILED",
        "POSITIONS_PREDECESSOR_MISSING",
        "POSITIONS",
    )


async def test_cash_entries_do_not_break_the_positions_zero_state(worker: Worker) -> None:
    worker.world.ledger.movements.append(cash_movement(D0, "10.00"))
    await worker.enqueue("POSITIONS", D1, D1)

    await worker.ring()

    assert await worker.statuses() == {D1: ("PROCESSED", None)}


async def test_an_all_run_failing_both_predecessors_keeps_the_positions_code(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {D0: ("FAILED", "FAILED")})
    request_id = await worker.enqueue("ALL", D1, D2)

    await worker.ring()

    assert await worker.statuses() == {D0: ("FAILED", "FAILED"), D1: ("FAILED", "FAILED")}
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "FAILED",
        "POSITIONS_PREDECESSOR_MISSING",
        D1,
        "POSITIONS",
    )


# --- ALL: one chain fails, the other continues (OQ-36, OQ-38, OQ-40) -----------------------


AGREEMENT_CASES = [
    # (scope, date_status seeded as {date: (portfolio, cash)}, cash on D0, trade on D0, state)
    ("CASH", {D0: (None, "PROCESSED")}, True, False, PredecessorState.PROCESSED),
    ("CASH", {D0: (None, "PROCESSED_WITH_ISSUES")}, True, False, "PROCESSED_WITH_ISSUES"),
    ("CASH", {D0: (None, "FAILED")}, False, False, PredecessorState.FAILED),
    ("CASH", {D0: (None, "RUNNING")}, False, False, PredecessorState.RUNNING),
    ("CASH", {date(2026, 10, 1): (None, "PROCESSED")}, False, False, "NOT_PROCESSED"),
    ("CASH", {}, True, False, PredecessorState.NOT_PROCESSED),  # a deposit on D0
    ("CASH", {}, False, False, PredecessorState.ZERO_STATE),
    ("POSITIONS", {}, True, False, PredecessorState.ZERO_STATE),  # cash entries only
    ("POSITIONS", {}, False, True, PredecessorState.NOT_PROCESSED),
    ("POSITIONS", {D0: ("FAILED", None)}, False, False, PredecessorState.FAILED),
]


@pytest.mark.parametrize(("scope", "seeded", "cash_on_d0", "trade_on_d0", "state"), AGREEMENT_CASES)
async def test_the_preview_and_the_run_apply_the_same_predecessor_rule(
    worker: Worker,
    scope: str,
    seeded: dict[date, tuple[str | None, str | None]],
    cash_on_d0: bool,
    trade_on_d0: bool,
    state: str,
) -> None:
    """H2: one rule. Whatever the preview reports for D1−1, the run of D1 follows it: it runs
    exactly when the preview's state allows it (OQ-31, OQ-37 item 4, OQ-40 item 5)."""
    await seed_statuses(worker.engine, seeded)
    if cash_on_d0:
        worker.world.ledger.movements.append(cash_movement(D0, "10.00"))
        worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("10.00"))
    if trade_on_d0:
        asset = await priced_asset(worker, D0, D1)
        worker.world.ledger.trades.append(trade(asset, D0, 1, "95000.0000000000"))

    preview = await worker.preview(scope, D1, D1)
    reported = preview.cash if scope == "CASH" else preview.positions
    request_id = await worker.enqueue(scope, D1, D1)
    await worker.ring()

    assert reported == state
    portfolio, cash = (await worker.statuses())[D1]
    ran = (cash if scope == "CASH" else portfolio) == "PROCESSED"
    assert ran is allows_run(reported)
    if not ran:
        assert (await worker.run_row(request_id))["error_code"] == f"{scope}_PREDECESSOR_MISSING"


async def test_a_technical_error_in_one_chain_rolls_back_only_that_chain(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D2))
    request_id = await worker.enqueue("ALL", D1, D3)

    await worker.ring()

    assert await worker.statuses() == {
        D1: ("PROCESSED", "PROCESSED"),
        D2: ("PROCESSED", "FAILED"),
        D3: ("PROCESSED", None),  # the failed chain's later dates are untouched
    }
    assert await worker.writes() == [
        (D1, "CASH", True),
        (D1, "POSITIONS", False),
        (D2, "POSITIONS", False),  # the cash write of D2 rolled back to its savepoint
        (D3, "POSITIONS", False),  # cash not processed on D3: AUM null
    ]
    run = await worker.run_row(request_id)
    assert run["status"] == "COMPLETED_WITH_ISSUES"
    assert (run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "PROCESSING_ERROR",
        D2,
        "CASH",
    )
    assert run["progress_date"] == D3


async def test_both_chains_failing_on_different_dates_ends_the_run_failed(worker: Worker) -> None:
    worker.writer.fail |= {("POSITIONS", D1), ("CASH", D2)}
    request_id = await worker.enqueue("ALL", D1, D3)

    await worker.ring()

    assert await worker.statuses() == {D1: ("FAILED", "PROCESSED"), D2: (None, "FAILED")}
    run = await worker.run_row(request_id)
    assert (run["status"], run["failed_date"], run["failed_chain"]) == ("FAILED", D1, "POSITIONS")
    assert run["progress_date"] == D1


async def test_a_failure_outside_the_chains_fails_the_date_for_every_live_chain(
    worker: Worker,
) -> None:
    worker.fail_reading_on_date_transaction = 2  # D2's transaction
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.ring()

    statuses = await worker.statuses()
    assert statuses[D2] == (None, "FAILED")
    assert D3 not in statuses
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        D2,
    )


# --- cancellation ---------------------------------------------------------------------------


async def request_cancel(worker: Worker, request_id: UUID) -> None:
    """``ProcessingService.request_cancel``, in its own transaction: a running run keeps RUNNING
    with ``cancel_requested_at`` set (OQ-46)."""
    await worker.cancel(request_id)


async def test_a_cancel_mid_run_commits_the_current_date_and_stops(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D3)

    async def cancel_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(request_cancel(worker, request_id)))
            await worker.wait_for_a_lock_waiter()  # the cancel waits on the run's row lock

    worker.writer.hook = cancel_during_d2
    pending: list[asyncio.Task[None]] = []

    await worker.ring()
    await asyncio.gather(*pending)

    assert await worker.statuses() == {D1: (None, "PROCESSED"), D2: (None, "PROCESSED")}
    run = await worker.run_row(request_id)
    assert run["status"] == "CANCELLED"
    assert run["progress_date"] == D2


async def test_a_cancel_during_the_last_date_lets_the_run_complete(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D2)

    async def cancel_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(request_cancel(worker, request_id)))
            await worker.wait_for_a_lock_waiter()  # the cancel waits on the run's row lock

    worker.writer.hook = cancel_during_d2
    pending: list[asyncio.Task[None]] = []

    await worker.ring()
    await asyncio.gather(*pending)

    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


# --- one worker: crash and recovery at startup (user decision, 2026-10-19) ----------------


async def test_startup_with_nothing_to_recover_or_queued_does_nothing(worker: Worker) -> None:
    await worker.restart()

    assert await worker.statuses() == {}
    assert await worker.writes() == []


async def test_a_crash_mid_date_resumes_after_progress_date(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D2: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D3)

    async def crash_on_d2(chain: str, day: date) -> None:
        if day == D2:
            raise asyncio.CancelledError  # the process dies: no Exception handler runs

    worker.writer.hook = crash_on_d2
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()

    rows = await worker.status_rows()
    assert (rows[D2]["cash"], rows[D2]["cash_previous"]) == ("RUNNING", "PROCESSED")
    assert (await worker.run_row(request_id))["progress_date"] == D1

    # The worker starts again: the run's command is sent again and the claim resumes at D2.
    worker.writer.hook = None
    await worker.restart()

    assert await worker.statuses() == {
        D0: (None, "PROCESSED"),
        D1: (None, "PROCESSED"),
        D2: (None, "PROCESSED"),
        D3: (None, "PROCESSED"),
    }
    assert [w[0] for w in await worker.writes()] == [D1, D2, D3]  # D1 is not processed again
    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


async def test_a_cancel_after_a_crash_restores_the_running_date(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D1: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D2)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()
    await request_cancel(worker, request_id)  # RUNNING keeps its status (OQ-46)
    worker.writer.hook = None

    await worker.restart()

    rows = await worker.status_rows()
    assert (rows[D1]["cash"], rows[D1]["cash_previous"]) == ("PROCESSED", None)
    assert (await worker.run_row(request_id))["status"] == "CANCELLED"


async def test_a_crash_on_a_new_date_deletes_its_row_when_the_run_ends(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()
    assert await worker.statuses() == {D1: (None, "RUNNING")}
    await request_cancel(worker, request_id)  # RUNNING keeps its status (OQ-46)

    await worker.restart()

    assert await worker.statuses() == {}


async def test_recovery_of_an_all_run_keeps_a_failed_chain_stopped(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D1))

    async def crash_on_d2(chain: str, day: date) -> None:
        if day == D2:
            raise asyncio.CancelledError

    worker.writer.hook = crash_on_d2
    request_id = await worker.enqueue("ALL", D1, D3)
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()

    worker.writer.hook = None
    await worker.restart()

    assert await worker.statuses() == {
        D1: ("PROCESSED", "FAILED"),
        D2: ("PROCESSED", None),
        D3: ("PROCESSED", None),
    }
    run = await worker.run_row(request_id)
    assert (run["status"], run["failed_chain"]) == ("COMPLETED_WITH_ISSUES", "CASH")


async def test_a_technical_error_on_a_single_chain_run_fails_the_run(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D2))
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.ring()

    assert await worker.statuses() == {D1: (None, "PROCESSED"), D2: (None, "FAILED")}
    assert await worker.writes() == [(D1, "CASH", False)]
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_chain"], run["progress_date"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        "CASH",
        D1,
    )


# --- review follow-ups: more adversarial sequences (plan §7, OQ-36, OQ-40) ----------------


async def test_one_chain_failing_its_predecessor_on_the_first_date_lets_the_other_go_on(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {D0: ("FAILED", None)})
    request_id = await worker.enqueue("ALL", D1, D2)

    await worker.ring()

    assert (await worker.statuses())[D1] == ("FAILED", "PROCESSED")
    assert (await worker.statuses())[D2] == (None, "PROCESSED")
    assert await worker.writes() == [(D1, "CASH", False), (D2, "CASH", False)]
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "COMPLETED_WITH_ISSUES",
        "POSITIONS_PREDECESSOR_MISSING",
        D1,
        "POSITIONS",
    )


async def test_a_cancelled_all_run_keeps_its_first_failure(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D1))
    request_id = await worker.enqueue("ALL", D1, D3)
    pending: list[asyncio.Task[None]] = []

    async def cancel_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(request_cancel(worker, request_id)))
            await worker.wait_for_a_lock_waiter()

    worker.writer.hook = cancel_during_d2
    await worker.ring()
    await asyncio.gather(*pending)

    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "CANCELLED",
        "PROCESSING_ERROR",
        D1,
        "CASH",
    )
    assert D3 not in await worker.statuses()


async def test_a_failure_outside_the_chains_after_one_stopped_fails_only_the_live_chain(
    worker: Worker,
) -> None:
    worker.writer.fail.add(("CASH", D1))
    worker.fail_reading_on_date_transaction = 2  # D2's transaction
    request_id = await worker.enqueue("ALL", D1, D3)

    await worker.ring()

    assert await worker.statuses() == {D1: ("PROCESSED", "FAILED"), D2: ("FAILED", None)}
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        D1,
        "CASH",
    )


async def test_a_deposit_landing_during_a_positions_run_changes_no_status(
    worker: Worker,
) -> None:
    async def deposit_during_d1(chain: str, day: date) -> None:
        if day == D1:
            worker.world.ledger.movements.append(cash_movement(D1, "500.00"))

    worker.writer.hook = deposit_during_d1
    await worker.enqueue("POSITIONS", D1, D2)

    await worker.ring()

    assert await worker.statuses() == {D1: ("PROCESSED", None), D2: ("PROCESSED", None)}


async def test_queue_a_backdated_trade_queue_b_cancel_a_finish_b(worker: Worker) -> None:
    asset = await priced_asset(worker, D1, D2, D3)
    first = await worker.enqueue("POSITIONS", D1, D3)
    assert await worker.take_next() == first
    pending: list[asyncio.Task[None]] = []

    async def cancel_a_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(worker.cancel(first)))
            await worker.wait_for_a_lock_waiter()  # the real cancel waits on A's row lock

    worker.writer.hook = cancel_a_during_d2
    worker.world.ledger.trades.append(trade(asset, D1, 3, "95000.0000000000"))  # backdated
    second = await worker.enqueue("POSITIONS", D1, D2)
    await worker.processor.run(first)
    await asyncio.gather(*pending)
    worker.writer.hook = None

    assert (await worker.run_row(first))["status"] == "CANCELLED"
    await worker.ring()

    assert (await worker.run_row(second))["status"] == "COMPLETED"
    assert await worker.statuses() == {D1: ("PROCESSED", None), D2: ("PROCESSED", None)}
    assert worker.world.portfolio.positions[D2].state.positions[0].quantity == 3


# --- merger review follow-ups (spec §13 cases 19 and 26; plan §7) -------------------------


async def test_case_19_a_cash_run_over_failed_positions_leaves_aum_null(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D1: ("FAILED", None)})
    await worker.enqueue("CASH", D1, D1)

    await worker.ring()

    assert await worker.statuses() == {D1: ("FAILED", "PROCESSED")}
    assert await worker.writes() == [(D1, "CASH", False)]  # FAILED is not processed (OQ-38)


async def test_case_26_an_earlier_failed_status_alone_fails_without_asking_the_ledger(
    worker: Worker,
) -> None:
    october_1, october_5 = date(2026, 10, 1), date(2026, 10, 5)
    await seed_statuses(worker.engine, {october_1: (None, "FAILED")})
    request_id = await worker.enqueue("CASH", october_5, october_5)

    await worker.ring()

    assert (await worker.statuses())[october_5] == (None, "FAILED")
    assert worker.world.ledger.asked == []
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "FAILED",
        "CASH_PREDECESSOR_MISSING",
        october_5,
        "CASH",
    )


# --- recovery at the worker start (OQ-45, OQ-46) ---------------------------------------


async def test_a_run_cancelled_while_taken_ends_cancelled_at_the_worker_start(
    worker: Worker,
) -> None:
    request_id = await worker.enqueue("CASH", D1, D2)
    assert await worker.take_next() == request_id  # the worker stopped before its first date
    await request_cancel(worker, request_id)

    await worker.restart()

    run = await worker.run_row(request_id)
    assert (run["status"], run["finished_at"]) == ("CANCELLED", worker.clock.now())
    assert await worker.statuses() == {}


async def test_a_running_run_with_a_cancel_request_at_the_worker_start_ends_cancelled(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D1: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D2)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()
    worker.writer.hook = None
    await request_cancel(worker, request_id)  # RUNNING keeps its status (OQ-46)
    writes_before = await worker.writes()

    await worker.restart()

    run = await worker.run_row(request_id)
    assert (run["status"], run["progress_date"]) == ("CANCELLED", None)
    rows = await worker.status_rows()
    assert (rows[D1]["cash"], rows[D1]["cash_previous"]) == ("PROCESSED", None)  # restored
    assert D2 not in rows
    assert await worker.writes() == writes_before  # no date processed


async def test_recovery_at_the_worker_start_is_idempotent(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D2)

    async def crash_on_d2(chain: str, day: date) -> None:
        if day == D2:
            raise asyncio.CancelledError

    worker.writer.hook = crash_on_d2
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()
    worker.writer.hook = None

    await worker.restart()
    after_first = (
        await worker.run_row(request_id),
        await worker.status_rows(),
        await worker.writes(),
    )
    await worker.restart()  # e.g. a stop raced with the end and the hook runs again

    assert after_first[0]["status"] == "COMPLETED"
    assert (
        await worker.run_row(request_id),
        await worker.status_rows(),
        await worker.writes(),
    ) == after_first


async def test_a_crash_mid_run_resumes_at_restart_then_drains_the_queue(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    first = await worker.enqueue("CASH", D1, D2)
    order: list[date] = []

    async def crash_on_d2(chain: str, day: date) -> None:
        order.append(day)
        if day == D2 and len(order) == 2:
            raise asyncio.CancelledError

    worker.writer.hook = crash_on_d2
    with pytest.raises(asyncio.CancelledError):
        await worker.ring()
    second = await worker.enqueue("CASH", D3, D3)  # queued while the worker is down

    await worker.restart()

    assert order == [D1, D2, D2, D3]  # D2 again (resumed after progress_date), then the queue
    assert (await worker.run_row(first))["status"] == "COMPLETED"
    assert (await worker.run_row(second))["status"] == "COMPLETED"


# --- recording the end of a run (a stuck queue otherwise) ---------------------------------


async def test_a_transient_failure_recording_the_end_is_retried(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D2)
    queued = await worker.enqueue("CASH", D3, D3)
    worker.store.end_failures = 2  # the third attempt succeeds

    await worker.ring()

    assert (await worker.run_row(request_id))["status"] == "COMPLETED"
    assert (await worker.run_row(queued))["status"] == "COMPLETED"
    assert worker.store.end_failures == 0


async def test_a_transient_failure_recording_a_failed_date_is_retried(worker: Worker) -> None:
    worker.fail_reading_on_date_transaction = 1  # D1 fails outside the chains
    request_id = await worker.enqueue("CASH", D1, D2)
    worker.store.end_failures = 1

    await worker.ring()

    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        D1,
    )
    assert await worker.statuses() == {D1: (None, "FAILED")}


async def test_a_persistent_failure_recording_the_end_escapes_and_the_restart_ends_the_run(
    worker: Worker,
) -> None:
    """The run stays RUNNING, and while it does no other run is taken: the error escapes so
    the worker process exits and restarts (Compose), and recovery at its start ends the run
    and drains the queue (OQ-45, OQ-46)."""
    request_id = await worker.enqueue("CASH", D1, D2)
    queued = await worker.enqueue("CASH", D3, D3)
    worker.store.end_failures = 3  # every attempt fails

    with pytest.raises(OperationalError, match="database blip"):
        await worker.ring()

    run = await worker.run_row(request_id)
    assert (run["status"], run["progress_date"]) == ("RUNNING", D2)
    assert (await worker.run_row(queued))["status"] == "QUEUED"
    assert await worker.statuses() == {D1: (None, "PROCESSED"), D2: (None, "PROCESSED")}

    await worker.restart()

    assert (await worker.run_row(request_id))["status"] == "COMPLETED"
    assert (await worker.run_row(queued))["status"] == "COMPLETED"
    assert [w[0] for w in await worker.writes()] == [D1, D2, D3]  # nothing processed twice


async def test_an_end_that_committed_before_its_error_is_not_written_twice(
    worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end commits, then a transient error (the connection drops before the COMMIT's
    answer arrives, say): the retry finds the run ended (`RunEndedError`) and writes nothing;
    the queue goes on."""
    request_id = await worker.enqueue("CASH", D1, D1)
    queued = await worker.enqueue("CASH", D2, D2)
    complete = worker.processor._complete
    calls: list[UUID] = []

    async def committed_then_failed(run_id: UUID) -> None:
        calls.append(run_id)
        await complete(run_id)
        if len(calls) == 1:
            raise OperationalError("COMMIT", {}, Exception("connection lost after commit"))

    monkeypatch.setattr(worker.processor, "_complete", committed_then_failed)
    await worker.ring()

    assert calls == [request_id, request_id, queued]  # one retry, then the next run
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"]) == ("COMPLETED", None)
    assert worker.store.end_attempts == 2  # the retry stopped at the lock: no second write
    assert (await worker.run_row(queued))["status"] == "COMPLETED"


async def test_a_bug_recording_the_end_is_not_retried_and_ends_the_run_failed(
    worker: Worker,
) -> None:
    """A deterministic error would recur on every retry and every restart, so the queue would
    stay blocked behind a RUNNING run: it is not retried, and the run ends FAILED with
    PROCESSING_ERROR in a fresh transaction; the dates it committed keep their statuses."""
    request_id = await worker.enqueue("CASH", D1, D2)
    queued = await worker.enqueue("CASH", D3, D3)
    worker.store.end_bugs = 1

    await worker.ring()

    assert worker.store.end_attempts == 3  # the end once, the FAILED end, then the next run
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["error_message"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        "Erro técnico ao processar a data.",
    )
    assert (run["progress_date"], run["failed_date"], run["finished_at"]) == (
        D2,
        None,  # no date failed
        worker.clock.now(),
    )
    assert await worker.statuses() == {
        D1: (None, "PROCESSED"),
        D2: (None, "PROCESSED"),
        D3: (None, "PROCESSED"),
    }
    assert (await worker.run_row(queued))["status"] == "COMPLETED"


async def test_a_bug_recording_a_failed_date_ends_the_run_failed_and_restores_the_date(
    worker: Worker,
) -> None:
    worker.fail_reading_on_date_transaction = 1  # D1 fails outside the chains
    request_id = await worker.enqueue("CASH", D1, D2)
    worker.store.end_bugs = 1  # recording D1's failure fails, not retried

    await worker.ring()

    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"]) == (
        "FAILED",
        "PROCESSING_ERROR",
        None,
    )
    assert await worker.statuses() == {}  # D1's RUNNING is restored: it had no status


async def test_a_bug_that_also_blocks_the_failed_end_escapes_for_a_restart(
    worker: Worker,
) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    worker.store.end_bugs = 2  # the end and the FAILED end both fail

    with pytest.raises(ValueError, match="bug while ending the run"):
        await worker.ring()

    assert (await worker.run_row(request_id))["status"] == "RUNNING"
    await worker.restart()
    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


async def test_a_cancel_committing_on_the_oldest_row_during_a_take_still_takes_the_next(
    worker: Worker,
) -> None:
    """A cancel that commits on the oldest QUEUED row while the take waits on its lock: the take
    must still take the next request (OQ-46). PostgreSQL re-checks the locked row; whether the
    same SELECT then returns the next row or none depends on the plan, so the take also selects
    again until it locks a row or none is queued."""
    oldest = await worker.enqueue("CASH", D1, D1)
    second = await worker.enqueue("CASH", D2, D2)

    async with worker.engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(  # as ProcessingService.request_cancel does first
            text("SELECT id FROM processing.requests WHERE id = :id FOR UPDATE"),
            {"id": oldest},
        )
        take = asyncio.create_task(worker.take_next())
        await worker.wait_for_a_lock_waiter()
        await connection.execute(
            text("UPDATE processing.requests SET status = 'CANCELLED' WHERE id = :id"),
            {"id": oldest},
        )
        await transaction.commit()

    async with asyncio.timeout(5):
        assert await take == second
    assert (await worker.run_row(second))["status"] == "RUNNING"
