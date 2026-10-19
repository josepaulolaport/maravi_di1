"""Processing runs end to end (spec §10, §13 cases 9, 10, 11, 14, 16, 18, 19, 20 and 26; OQ-21,
OQ-23, OQ-26, OQ-29, OQ-30, OQ-31, OQ-32, OQ-36, OQ-37, OQ-38, OQ-40, OQ-45, OQ-46): requests are
queued over HTTP, the one worker drains them oldest first in-process, and the outcome is read
back through ``/api``. Technical errors inside a chain or outside every chain (cases 24 and 25)
cannot be caused through the API; they are covered by ``tests/integration/processing/``.

Today is Friday 08/01/2027; DI1F28 matures on 01/01/2028. Trades and prices are typed as PU.

The predecessor rule (spec §10.1, OQ-31): a date D of a chain is processed only when D−1 is
Processado (with or without pendências) or the chain's zero state (no earlier status for the
chain and no entry of its type up to D−1); otherwise D gets Erro with
``CASH_PREDECESSOR_MISSING`` or ``POSITIONS_PREDECESSOR_MISSING`` and "Dia anterior não
processado", and later dates are not touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import acceptance_app, problem

TODAY = date(2027, 1, 8)
MON, TUE, WED, THU = (date(2027, 1, d) for d in (4, 5, 6, 7))
CASH_MISSING = "CASH_PREDECESSOR_MISSING"
POSITIONS_MISSING = "POSITIONS_PREDECESSOR_MISSING"
PREDECESSOR_MESSAGE = "Dia anterior não processado"


@pytest.fixture
def desk() -> Iterator[Desk]:
    with acceptance_app(TODAY) as (client, database_url):
        yield Desk(client, database_url, TODAY)


@pytest.fixture
def di1f28(desk: Desk) -> str:
    asset = desk.contract("DI1F28", "2028-01-01")
    for day, pu in ((MON, "90100"), (TUE, "90200"), (WED, "90300"), (THU, "90400")):
        desk.price(asset, day, pu=pu)
    return asset


def _failure(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run["status"],
        run["error_code"],
        run["error_message"],
        run["failed_date"],
        run["failed_chain"],
    )


def _carteira(desk: Desk, days: tuple[date, ...]) -> list[dict[str, Any]]:
    """Every figure, status and processing time the Carteira shows for ``days``."""
    return [desk.summary(d) | {"rows": desk.positions(d)} for d in days]


# Cases 9 and 16, second halves: writes after a run change nothing processed (OQ-31, OQ-32) ----


def test_writes_after_a_run_leave_every_processed_date_unchanged(desk: Desk, di1f28: str) -> None:
    desk.cash(MON, "200000")
    first = desk.trade(di1f28, MON, 2, pu="90000")
    run = desk.process("ALL", MON, WED)
    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    statuses = desk.statuses()
    assert statuses == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE, WED)}
    processed = _carteira(desk, (MON, TUE, WED))
    # The figures are the run's: cash 200000 − 180000 = 20000; MV 2 × 90300; AUM 200600.
    assert desk.aum(WED) == Decimal(200600)

    # A new trade and a deposit on processed dates, a corrected price, a deleted entry.
    desk.trade(di1f28, TUE, -1, pu="90500")
    desk.cash(WED, "1000")
    desk.price(di1f28, TUE, pu="95000")
    deleted = desk.client.post("/api/ledger/entries/deletions", json={"ids": [first["id"]]})
    assert deleted.status_code == 204, deleted.text

    # Only the facts were saved: no job, no status, time or figure changed (spec §13 cases 9, 16).
    assert [r["id"] for r in desk.client.get("/api/processing/requests").json()["items"]] == [
        run["id"]
    ]
    assert desk.statuses() == statuses
    current = _carteira(desk, (MON, TUE, WED))
    # The Carteira shows the current price beside the old figures (OQ-30): only that differs.
    assert current[1]["rows"]["DI1F28"]["reference_pu"] == Decimal(95000)
    current[1]["rows"]["DI1F28"] |= {
        k: processed[1]["rows"]["DI1F28"][k] for k in ("reference_pu", "reference_rate")
    }
    assert current == processed


# Case 10: the queue, cancellation and validation (OQ-29, OQ-30, OQ-46) --------------------------


def test_overlapping_requests_run_one_after_the_other_oldest_first(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")
    older = desk.queue("ALL", MON, WED)
    newer = desk.queue("ALL", TUE, THU)

    desk.work()  # one worker drains the queue (OQ-46)

    first, second = desk.run(older["id"]), desk.run(newer["id"])
    assert (first["status"], second["status"]) == ("COMPLETED", "COMPLETED")
    assert datetime.fromisoformat(first["finished_at"]) <= datetime.fromisoformat(
        second["started_at"]
    )
    assert desk.statuses() == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE, WED, THU)}
    # Each request processed exactly its range, the overlap twice (OQ-11): Thursday continues
    # from Wednesday, 1 × (90400 − 90300) = 100.
    assert desk.portfolio_pnl(THU)["daily_pnl"] == Decimal(100)


def test_a_queued_request_is_cancelled_at_once_and_never_runs(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")
    queued = desk.queue("ALL", MON, TUE)

    cancelled = desk.client.post(f"/api/processing/requests/{queued['id']}/cancel")

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    desk.work()
    assert desk.run(queued["id"])["status"] == "CANCELLED"
    assert desk.statuses() == {}
    # A new request is a separate action (no cancel-and-replace, OQ-30).
    again = desk.process("ALL", MON, TUE)
    assert again["status"] == "COMPLETED", again
    assert desk.statuses() == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE)}


def test_a_finished_request_cannot_be_cancelled(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")
    run = desk.process("ALL", MON, MON)
    assert run["status"] == "COMPLETED", run

    response = desk.client.post(f"/api/processing/requests/{run['id']}/cancel")

    assert problem(response, 409) == [("JOB_NOT_CANCELLABLE", None)]
    assert desk.run(run["id"])["status"] == "COMPLETED"


def test_a_range_ending_after_today_is_refused(desk: Desk) -> None:
    response = desk.client.post(
        "/api/processing/requests",
        json={"scope": "ALL", "start_date": "2027-01-08", "end_date": "2027-01-09"},
    )

    assert problem(response, 422) == [("FUTURE_DATE", "end_date")]  # OQ-29
    assert desk.client.get("/api/processing/requests").json()["items"] == []


# Case 11: recovery at the start of the one worker (OQ-45, OQ-46) -------------------------------


def test_an_interrupted_run_resumes_after_its_progress_date(desk: Desk, di1f28: str) -> None:
    # The worker stopped after committing Monday of a Monday-to-Wednesday run. That state is set
    # directly (a crash cannot be caused through the API): Monday published by an earlier run,
    # the request left RUNNING with progress_date Monday.
    desk.trade(di1f28, MON, 1, pu="90000")
    monday = desk.process("ALL", MON, MON)
    assert monday["status"] == "COMPLETED", monday
    monday_time = desk.summary(MON)["positions"]["published_at"]
    interrupted = desk.queue("ALL", MON, WED)
    desk.sql(
        "UPDATE processing.requests SET status = 'RUNNING', started_at = now(),"
        " progress_date = %s WHERE id = %s",
        (MON, interrupted["id"]),
    )

    restarted_at = desk.work()

    run = desk.run(interrupted["id"])
    assert (run["status"], run["error_code"], run["progress_date"]) == (
        "COMPLETED",
        None,
        WED.isoformat(),
    ), run
    assert desk.statuses() == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE, WED)}
    # Monday is not run again; Tuesday and Wednesday are processed by the recovery.
    assert desk.summary(MON)["positions"]["published_at"] == monday_time
    for day in (TUE, WED):
        assert datetime.fromisoformat(desk.summary(day)["positions"]["published_at"]) == (
            restarted_at
        )
    assert desk.portfolio_pnl(WED)["cumulative_pnl"] == Decimal(300)  # 1 × (90300 − 90000)


def test_an_interrupted_run_with_a_cancel_request_ends_cancelled(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")
    interrupted = desk.queue("ALL", MON, WED)
    desk.sql(
        "UPDATE processing.requests SET status = 'RUNNING', started_at = now(),"
        " cancel_requested_at = now() WHERE id = %s",
        (interrupted["id"],),
    )
    later = desk.queue("ALL", MON, MON)

    desk.work()

    # Recovery ends the cancelled run before any date, then the queue is drained (OQ-46).
    assert desk.run(interrupted["id"])["status"] == "CANCELLED"
    assert desk.run(later["id"])["status"] == "COMPLETED"
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED")}


# Case 14: the predecessor rule per day and per chain (OQ-31, OQ-36, OQ-40) ----------------------


def test_cash_without_its_predecessor_fails_and_later_dates_are_untouched(desk: Desk) -> None:
    desk.cash(MON, "1000")

    run = desk.process("CASH", TUE, WED)

    assert _failure(run) == ("FAILED", CASH_MISSING, PREDECESSOR_MESSAGE, TUE.isoformat(), "CASH")
    assert desk.statuses() == {TUE: ("FAILED", None)}


def test_positions_without_their_predecessor_fail(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")

    run = desk.process("POSITIONS", TUE, WED)

    assert _failure(run) == (
        "FAILED",
        POSITIONS_MISSING,
        PREDECESSOR_MESSAGE,
        TUE.isoformat(),
        "POSITIONS",
    )
    assert desk.statuses() == {TUE: (None, "FAILED")}


def test_all_with_one_chain_failing_writes_the_other_and_has_no_aum(
    desk: Desk, di1f28: str
) -> None:
    # A deposit on Monday and no trade before Tuesday: the cash chain fails on Tuesday, the
    # positions chain starts from its zero state and runs to the end (OQ-36); AUM stays null
    # on Tuesday and Wednesday (case 18, OQ-38).
    desk.cash(MON, "200000")
    desk.trade(di1f28, TUE, 1, pu="90000")

    run = desk.process("ALL", TUE, WED)

    assert _failure(run) == (
        "COMPLETED_WITH_ISSUES",
        CASH_MISSING,
        PREDECESSOR_MESSAGE,
        TUE.isoformat(),
        "CASH",
    )
    assert desk.statuses() == {TUE: ("FAILED", "PROCESSED"), WED: (None, "PROCESSED")}
    # Positions: trades 1 × (90200 − 90000) = 200 on Tuesday, position 1 × 100 on Wednesday.
    assert desk.portfolio_pnl(WED)["cumulative_pnl"] == Decimal(300)
    assert (desk.aum(TUE), desk.aum(WED)) == (None, None)

    # "Solicitar novo processamento" with the failed chain's scope, from Monday this time: the
    # cash chain starts from its zero state and AUM appears (cash 200000 − 90000 = 110000).
    retry = desk.process("CASH", MON, WED)

    assert (retry["status"], retry["error_code"]) == ("COMPLETED", None), retry
    assert desk.statuses() == {
        MON: ("PROCESSED", None),
        TUE: ("PROCESSED", "PROCESSED"),
        WED: ("PROCESSED", "PROCESSED"),
    }
    assert desk.aum(TUE) == Decimal(110000) + Decimal(90200)
    assert desk.aum(WED) == Decimal(110000) + Decimal(90300)


def test_all_with_both_chains_failing_on_the_same_date(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000")

    run = desk.process("ALL", TUE, WED)

    assert (run["status"], run["error_code"], run["failed_date"]) == (
        "FAILED",
        POSITIONS_MISSING,
        TUE.isoformat(),
    ), run
    assert desk.statuses() == {TUE: ("FAILED", "FAILED")}


def test_a_failed_predecessor_counts_as_not_processed(desk: Desk) -> None:
    desk.cash(MON, "1000")
    failed = desk.process("CASH", TUE, TUE)
    assert failed["status"] == "FAILED", failed

    run = desk.process("CASH", WED, WED)

    assert _failure(run) == ("FAILED", CASH_MISSING, PREDECESSOR_MESSAGE, WED.isoformat(), "CASH")
    assert desk.statuses() == {TUE: ("FAILED", None), WED: ("FAILED", None)}


def test_cash_over_dates_whose_positions_failed_has_no_aum(desk: Desk, di1f28: str) -> None:
    # Case 19 (OQ-38): positions of Tuesday are Erro; a CASH run writes the cash, AUM stays null.
    desk.trade(di1f28, MON, 1, pu="90000")
    failed = desk.process("ALL", TUE, TUE)
    assert failed["status"] == "FAILED", failed

    run = desk.process("CASH", MON, TUE)

    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    assert desk.statuses() == {MON: ("PROCESSED", None), TUE: ("PROCESSED", "FAILED")}
    assert desk.cash_balance(TUE) == Decimal(-90000)
    assert desk.aum(TUE) is None


# Cases 20 and 26: a gap after an earlier status fails D without asking Ledger (OQ-37, OQ-40) ----


def test_a_gap_in_the_chain_fails_the_date(desk: Desk) -> None:
    desk.cash(MON, "1000")
    monday = desk.process("CASH", MON, MON)
    assert monday["status"] == "COMPLETED", monday

    run = desk.process("CASH", WED, WED)

    assert _failure(run) == ("FAILED", CASH_MISSING, PREDECESSOR_MESSAGE, WED.isoformat(), "CASH")
    assert desk.statuses() == {MON: ("PROCESSED", None), WED: ("FAILED", None)}


def test_an_only_failed_status_is_not_the_zero_state(desk: Desk) -> None:
    # Case 26: the cash chain's only status is Erro on Tuesday and no entry is left; a CASH run
    # on Thursday still fails, because an earlier date of the chain has a status.
    deposit = desk.cash(MON, "1000", at="09:00")
    failed = desk.process("CASH", TUE, TUE)
    assert failed["status"] == "FAILED", failed
    deleted = desk.client.post("/api/ledger/entries/deletions", json={"ids": [deposit["id"]]})
    assert deleted.status_code == 204, deleted.text

    run = desk.process("CASH", THU, THU)

    assert _failure(run) == ("FAILED", CASH_MISSING, PREDECESSOR_MESSAGE, THU.isoformat(), "CASH")
    assert desk.statuses() == {TUE: ("FAILED", None), THU: ("FAILED", None)}
