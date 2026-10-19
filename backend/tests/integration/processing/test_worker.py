"""The dispatcher and the worker on PostgreSQL (plan §7 Wave 4 and its adversarial sequences;
interfaces.md "Processing", "Transaction boundaries" 3 to 7; OQ-5, OQ-23, OQ-26, OQ-31, OQ-36 to
OQ-40)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from di1.modules.ledger.public import EntryType
from di1.modules.portfolio.public import CashBalance
from di1.modules.prices.public import PriceSource
from di1.modules.processing.application.services.dispatcher import ProcessingDispatcher
from di1.modules.processing.infrastructure.persistence.run_store import SqlRunStore
from di1.platform.database.unit_of_work import unit_of_work_factory
from tests.integration.processing.support import make_service, seed_instrument, seed_statuses
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


# --- dispatcher -----------------------------------------------------------------------------


async def test_dispatch_takes_the_oldest_queued_run_and_writes_the_command(worker: Worker) -> None:
    first = await worker.enqueue("CASH", D1, D1)
    await worker.enqueue("CASH", D2, D2)

    assert await worker.dispatcher.dispatch_next() == first

    row = await worker.run_row(first)
    assert row["status"] == "DISPATCHED"
    assert row["dispatched_at"] == worker.clock.now()
    assert await worker.active_request_id() == first
    assert await worker.outbox() == [("processing.run_request", {"request_id": str(first)})]


async def test_only_one_run_is_active_at_a_time(worker: Worker) -> None:
    await worker.enqueue("CASH", D1, D1)
    second = await worker.enqueue("CASH", D2, D2)
    await worker.dispatcher.dispatch_next()

    assert await worker.dispatcher.dispatch_next() is None
    assert (await worker.run_row(second))["status"] == "QUEUED"
    assert len(await worker.outbox()) == 1


async def test_an_empty_queue_dispatches_nothing(worker: Worker) -> None:
    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.outbox() == []


async def test_the_next_run_is_dispatched_once_the_active_one_ends(worker: Worker) -> None:
    first = await worker.enqueue("CASH", D1, D1)
    second = await worker.enqueue("CASH", D2, D2)

    await worker.dispatch_and_run()

    assert (await worker.run_row(first))["status"] == "COMPLETED"
    assert await worker.dispatcher.dispatch_next() == second
    assert await worker.active_request_id() == second


async def test_the_dispatcher_frees_the_slot_of_an_ended_run(worker: Worker) -> None:
    first = await worker.enqueue("CASH", D1, D1)
    await worker.dispatch_and_run()
    assert await worker.active_request_id() == first  # the worker never locks the slot

    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.active_request_id() is None


# --- a run end to end -----------------------------------------------------------------------


async def test_a_cash_run_from_the_zero_state_processes_every_date(worker: Worker) -> None:
    worker.world.ledger.movements.append(cash_movement(D1, "1000.00"))
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.dispatch_and_run()

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
    assert run["attempt_count"] == 1
    assert run["finished_at"] is not None
    assert run["error_code"] is None
    # A CASH run: AUM follows the positions status of each date, here not processed (OQ-38).
    assert await worker.writes() == [(D1, "CASH", False), (D2, "CASH", False), (D3, "CASH", False)]


async def test_a_cash_run_counts_positions_processed_by_another_run(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D1: ("PROCESSED", None)})
    await worker.enqueue("CASH", D1, D1)

    await worker.dispatch_and_run()

    assert await worker.writes() == [(D1, "CASH", True)]


async def test_an_all_run_writes_positions_first_then_cash_with_its_outcome(
    worker: Worker,
) -> None:
    asset = await priced_asset(worker, D1, D2)
    worker.world.ledger.trades.append(trade(asset, D1, 10, "95000.0000000000"))
    request_id = await worker.enqueue("ALL", D1, D2)

    await worker.dispatch_and_run()

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

    await worker.dispatch_and_run()

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
    await worker.dispatch_and_run()
    assert await worker.issues() == [("MISSING_REFERENCE_PRICE", D1, D1)]

    worker.world.prices.set(asset, D1, "95000.0000000000")
    second = await worker.enqueue("POSITIONS", D1, D1)
    await worker.dispatch_and_run()

    assert await worker.issues() == []
    assert await worker.statuses() == {D1: ("PROCESSED", None)}
    assert (await worker.run_row(second))["status"] == "COMPLETED"


# --- predecessor rule (OQ-31, OQ-37 item 4, OQ-40 item 5) -----------------------------------


async def test_a_gap_before_the_first_date_fails_it_without_asking_the_ledger(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {date(2026, 10, 1): (None, "PROCESSED")})
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.dispatch_and_run()

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
    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.active_request_id() is None


@pytest.mark.parametrize("previous", ["FAILED", "RUNNING"])
async def test_a_failed_or_running_day_before_fails_the_date(worker: Worker, previous: str) -> None:
    await seed_statuses(worker.engine, {D0: (None, previous)})
    request_id = await worker.enqueue("CASH", D1, D1)

    await worker.dispatch_and_run()

    assert (await worker.statuses())[D1] == (None, "FAILED")
    assert worker.world.ledger.asked == []
    assert (await worker.run_row(request_id))["error_code"] == "CASH_PREDECESSOR_MISSING"


async def test_entries_before_an_unprocessed_first_date_fail_it(worker: Worker) -> None:
    asset = await priced_asset(worker)
    worker.world.ledger.trades.append(trade(asset, D0, 1, "95000.0000000000"))
    request_id = await worker.enqueue("POSITIONS", D1, D2)

    await worker.dispatch_and_run()

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

    await worker.dispatch_and_run()

    assert await worker.statuses() == {D1: ("PROCESSED", None)}


async def test_an_all_run_failing_both_predecessors_keeps_the_positions_code(
    worker: Worker,
) -> None:
    await seed_statuses(worker.engine, {D0: ("FAILED", "FAILED")})
    request_id = await worker.enqueue("ALL", D1, D2)

    await worker.dispatch_and_run()

    assert await worker.statuses() == {D0: ("FAILED", "FAILED"), D1: ("FAILED", "FAILED")}
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "FAILED",
        "POSITIONS_PREDECESSOR_MISSING",
        D1,
        "POSITIONS",
    )


# --- ALL: one chain fails, the other continues (OQ-36, OQ-38, OQ-40) -----------------------


async def test_a_technical_error_in_one_chain_rolls_back_only_that_chain(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D2))
    request_id = await worker.enqueue("ALL", D1, D3)

    await worker.dispatch_and_run()

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

    await worker.dispatch_and_run()

    assert await worker.statuses() == {D1: ("FAILED", "PROCESSED"), D2: (None, "FAILED")}
    run = await worker.run_row(request_id)
    assert (run["status"], run["failed_date"], run["failed_chain"]) == ("FAILED", D1, "POSITIONS")
    assert run["progress_date"] == D1


async def test_a_failure_outside_the_chains_fails_the_date_for_every_live_chain(
    worker: Worker,
) -> None:
    worker.fail_reading_on_date_transaction = 2  # D2's transaction
    request_id = await worker.enqueue("CASH", D1, D3)

    await worker.dispatch_and_run()

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
    """What ``ProcessingService.request_cancel`` does to a running run, in its own
    transaction."""
    await worker.execute(
        "UPDATE processing.requests SET status = 'CANCELLING', cancel_requested_at = now()"
        " WHERE id = :id",
        id=request_id,
    )


async def test_a_run_cancelled_before_it_started_ends_at_the_claim(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D3)
    await worker.dispatcher.dispatch_next()
    await worker.execute(
        "UPDATE processing.requests SET status = 'CANCELLING', cancel_requested_at = now()"
        " WHERE id = :id",
        id=request_id,
    )

    assert await worker.claim(request_id) is None

    run = await worker.run_row(request_id)
    assert run["status"] == "CANCELLED"
    assert run["started_at"] is None
    assert await worker.statuses() == {}
    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.active_request_id() is None


async def test_a_cancel_mid_run_commits_the_current_date_and_stops(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D3)

    async def cancel_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(request_cancel(worker, request_id)))
            await worker.wait_for_a_lock_waiter()  # the cancel waits on the run's row lock

    worker.writer.hook = cancel_during_d2
    pending: list[asyncio.Task[None]] = []

    await worker.dispatch_and_run()
    await asyncio.gather(*pending)

    assert await worker.statuses() == {D1: (None, "PROCESSED"), D2: (None, "PROCESSED")}
    run = await worker.run_row(request_id)
    assert run["status"] == "CANCELLED"
    assert run["progress_date"] == D2
    assert await worker.dispatcher.dispatch_next() is None
    assert await worker.active_request_id() is None


async def test_a_cancel_during_the_last_date_lets_the_run_complete(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D2)

    async def cancel_during_d2(chain: str, day: date) -> None:
        if day == D2:
            pending.append(asyncio.create_task(request_cancel(worker, request_id)))
            await worker.wait_for_a_lock_waiter()  # the cancel waits on the run's row lock

    worker.writer.hook = cancel_during_d2
    pending: list[asyncio.Task[None]] = []

    await worker.dispatch_and_run()
    await asyncio.gather(*pending)

    assert (await worker.run_row(request_id))["status"] == "COMPLETED"


# --- one worker: crash and recovery at startup (user decision, 2026-10-19) ----------------


async def test_a_command_for_a_run_that_ended_does_nothing(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.dispatch_and_run()

    assert await worker.claim(request_id) is None
    run = await worker.run_row(request_id)
    assert (run["status"], run["attempt_count"]) == ("COMPLETED", 1)


async def test_the_dispatcher_never_re_dispatches_an_active_run(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    await worker.dispatcher.dispatch_next()
    assert await worker.claim(request_id) is not None
    worker.clock.advance(3600)

    assert await worker.dispatcher.dispatch_next() is None
    assert len(await worker.outbox()) == 1


async def test_startup_with_nothing_active_recovers_nothing(worker: Worker) -> None:
    await worker.enqueue("CASH", D1, D1)

    assert await worker.dispatcher.recover_interrupted() is None
    assert await worker.outbox() == []


async def test_a_crash_mid_date_resumes_after_progress_date(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D2: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D3)

    async def crash_on_d2(chain: str, day: date) -> None:
        if day == D2:
            raise asyncio.CancelledError  # the process dies: no Exception handler runs

    worker.writer.hook = crash_on_d2
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()

    rows = await worker.status_rows()
    assert (rows[D2]["cash"], rows[D2]["cash_previous"]) == ("RUNNING", "PROCESSED")
    assert (await worker.run_row(request_id))["progress_date"] == D1

    # The worker starts again: the run's command is sent again and the claim resumes at D2.
    worker.writer.hook = None
    assert await worker.restart_and_run() == request_id

    assert await worker.statuses() == {
        D0: (None, "PROCESSED"),
        D1: (None, "PROCESSED"),
        D2: (None, "PROCESSED"),
        D3: (None, "PROCESSED"),
    }
    assert [w[0] for w in await worker.writes()] == [D1, D2, D3]  # D1 is not processed again
    run = await worker.run_row(request_id)
    assert (run["status"], run["attempt_count"]) == ("COMPLETED", 2)


async def test_a_cancel_after_a_crash_restores_the_running_date(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D1: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D2)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()
    await worker.execute(
        "UPDATE processing.requests SET status = 'CANCELLING', cancel_requested_at = now()"
        " WHERE id = :id",
        id=request_id,
    )
    worker.writer.hook = None

    await worker.restart_and_run()

    rows = await worker.status_rows()
    assert (rows[D1]["cash"], rows[D1]["cash_previous"]) == ("PROCESSED", None)
    assert (await worker.run_row(request_id))["status"] == "CANCELLED"


async def test_a_crash_on_a_new_date_deletes_its_row_when_the_run_ends(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()
    assert await worker.statuses() == {D1: (None, "RUNNING")}
    await worker.execute(
        "UPDATE processing.requests SET status = 'CANCELLING', cancel_requested_at = now()"
        " WHERE id = :id",
        id=request_id,
    )

    await worker.restart_and_run()

    assert await worker.statuses() == {}


async def test_recovery_of_an_all_run_keeps_a_failed_chain_stopped(worker: Worker) -> None:
    worker.writer.fail.add(("CASH", D1))

    async def crash_on_d2(chain: str, day: date) -> None:
        if day == D2:
            raise asyncio.CancelledError

    worker.writer.hook = crash_on_d2
    request_id = await worker.enqueue("ALL", D1, D3)
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()

    worker.writer.hook = None
    await worker.restart_and_run()

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

    await worker.dispatch_and_run()

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

    await worker.dispatch_and_run()

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
    await worker.dispatch_and_run()
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

    await worker.dispatch_and_run()

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

    await worker.dispatch_and_run()

    assert await worker.statuses() == {D1: ("PROCESSED", None), D2: ("PROCESSED", None)}


async def test_queue_a_backdated_trade_queue_b_cancel_a_finish_b(worker: Worker) -> None:
    service = make_service()
    asset = await priced_asset(worker, D1, D2, D3)
    first = await worker.enqueue("POSITIONS", D1, D3)
    assert await worker.dispatcher.dispatch_next() == first
    claim = await worker.claim(first)
    assert claim is not None
    pending: list[asyncio.Task[None]] = []

    async def cancel_a_during_d2(chain: str, day: date) -> None:
        if day == D2:

            async def cancel() -> None:
                async with worker.uow_factory() as uow:
                    await service.request_cancel(first, uow=uow)

            pending.append(asyncio.create_task(cancel()))
            await worker.wait_for_a_lock_waiter()  # the real cancel waits on A's row lock

    worker.writer.hook = cancel_a_during_d2
    worker.world.ledger.trades.append(trade(asset, D1, 3, "95000.0000000000"))  # backdated
    second = await worker.enqueue("POSITIONS", D1, D2)
    await worker.processor.run(claim.request_id)
    await asyncio.gather(*pending)
    worker.writer.hook = None

    assert (await worker.run_row(first))["status"] == "CANCELLED"
    assert await worker.dispatch_and_run() == second

    assert (await worker.run_row(second))["status"] == "COMPLETED"
    assert await worker.statuses() == {D1: ("PROCESSED", None), D2: ("PROCESSED", None)}
    assert worker.world.portfolio.positions[D2].state.positions[0].quantity == 3


# --- merger review follow-ups (spec §13 cases 19 and 26; plan §7) -------------------------


async def test_case_19_a_cash_run_over_failed_positions_leaves_aum_null(worker: Worker) -> None:
    await seed_statuses(worker.engine, {D1: ("FAILED", None)})
    await worker.enqueue("CASH", D1, D1)

    await worker.dispatch_and_run()

    assert await worker.statuses() == {D1: ("FAILED", "PROCESSED")}
    assert await worker.writes() == [(D1, "CASH", False)]  # FAILED is not processed (OQ-38)


async def test_case_26_an_earlier_failed_status_alone_fails_without_asking_the_ledger(
    worker: Worker,
) -> None:
    october_1, october_5 = date(2026, 10, 1), date(2026, 10, 5)
    await seed_statuses(worker.engine, {october_1: (None, "FAILED")})
    request_id = await worker.enqueue("CASH", october_5, october_5)

    await worker.dispatch_and_run()

    assert (await worker.statuses())[october_5] == (None, "FAILED")
    assert worker.world.ledger.asked == []
    run = await worker.run_row(request_id)
    assert (run["status"], run["error_code"], run["failed_date"], run["failed_chain"]) == (
        "FAILED",
        "CASH_PREDECESSOR_MISSING",
        october_5,
        "CASH",
    )


async def test_a_command_lost_after_the_outbox_publish_is_sent_again_at_startup(
    worker: Worker,
) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)
    assert await worker.dispatcher.dispatch_next() == request_id
    # The relay published the command and the worker never claimed it (lost, or it crashed).
    assert await worker.dispatcher.dispatch_next() is None

    assert await worker.restart_and_run() == request_id

    assert len(await worker.outbox()) == 2
    run = await worker.run_row(request_id)
    assert (run["status"], run["attempt_count"]) == ("COMPLETED", 1)


# --- recovery cap (user decision, 2026-10-19) -------------------------------------------


async def crashed_run(worker: Worker, *, attempts: int) -> UUID:
    """A CASH run over D1..D2 that crashed on D1, leaving D1 RUNNING over PROCESSED, after
    ``attempts`` claims."""
    await seed_statuses(worker.engine, {D0: (None, "PROCESSED"), D1: (None, "PROCESSED")})
    worker.world.portfolio.cash[D0] = CashBalance(as_of=D0, balance=Decimal("0"))
    request_id = await worker.enqueue("CASH", D1, D2)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()
    worker.writer.hook = None
    await worker.execute(
        "UPDATE processing.requests SET attempt_count = :n WHERE id = :id",
        n=attempts,
        id=request_id,
    )
    return request_id


async def test_a_run_past_the_recovery_cap_ends_failed_and_frees_the_slot(
    worker: Worker,
) -> None:
    stuck = await crashed_run(worker, attempts=4)  # the first claim and 3 recoveries
    queued = await worker.enqueue("CASH", D2, D2)
    outbox_before = len(await worker.outbox())

    assert await worker.dispatcher.recover_interrupted() == queued

    run = await worker.run_row(stuck)
    assert (run["status"], run["error_code"], run["error_message"]) == (
        "FAILED",
        "RECOVERY_EXHAUSTED",
        "Processamento interrompido após repetidas falhas de recuperação.",
    )
    assert run["finished_at"] == worker.clock.now()
    rows = await worker.status_rows()
    assert (rows[D1]["cash"], rows[D1]["cash_previous"]) == ("PROCESSED", None)  # restored
    assert await worker.active_request_id() == queued
    assert len(await worker.outbox()) == outbox_before + 1  # only the queued run's command
    assert (await worker.run_row(queued))["status"] == "DISPATCHED"


async def test_a_run_below_the_recovery_cap_is_still_re_dispatched(worker: Worker) -> None:
    stuck = await crashed_run(worker, attempts=3)

    assert await worker.dispatcher.recover_interrupted() == stuck
    assert (await worker.run_row(stuck))["status"] == "RUNNING"


async def test_the_recovery_cap_is_configurable(
    worker: Worker, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    stuck = await crashed_run(worker, attempts=2)
    dispatcher = ProcessingDispatcher(
        uow_factory=unit_of_work_factory(session_factory),
        store=SqlRunStore(worker.clock),
        clock=worker.clock,
        max_recovery_attempts=1,
    )

    assert await dispatcher.recover_interrupted() is None

    run = await worker.run_row(stuck)
    assert (run["status"], run["error_code"]) == ("FAILED", "RECOVERY_EXHAUSTED")
    assert await worker.active_request_id() is None


async def test_a_crash_on_a_new_date_past_the_cap_deletes_its_empty_row(worker: Worker) -> None:
    request_id = await worker.enqueue("CASH", D1, D1)

    async def crash(chain: str, day: date) -> None:
        raise asyncio.CancelledError

    worker.writer.hook = crash
    with pytest.raises(asyncio.CancelledError):
        await worker.dispatch_and_run()
    await worker.execute(
        "UPDATE processing.requests SET attempt_count = 4 WHERE id = :id", id=request_id
    )

    await worker.dispatcher.recover_interrupted()

    assert await worker.statuses() == {}
    assert (await worker.run_row(request_id))["status"] == "FAILED"
