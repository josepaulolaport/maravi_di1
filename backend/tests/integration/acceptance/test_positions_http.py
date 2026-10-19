"""Spec §13 cases 2 and 3 end to end: buy, increase, partial sale, crossing zero and full close
with intraday order; average PU and average rate each by its own weighting (spec §7.2; OQ-3,
OQ-10, OQ-13, OQ-24). Entries and prices go through ``/api``; one ALL run per scenario is queued
over HTTP and drained by the worker in-process; the Carteira is read back.

Today is Friday 08/01/2027; DI1F28 matures on 01/01/2028 (Monday 04/01/2027 is 362 calendar days
before it). Trades are typed as PU, so each execution rate is spec §4.1's
``(100000/PU)^(365/dias) − 1`` at 12 places (`expected_rate`). An average is a calculated PU or
rate, so it is stored at 10 or 12 places, half-up (OQ-3 item 2: "a calculated PU is stored
with 10 dp, a calculated rate with 12 dp").

    Mon 10:00  buy  1 @ 90000                 Q 1
    Mon 11:00  buy  3 @ 91000                 Q 4, avg PU (90000 + 3×91000)/4 = 90750,
                                              avg rate (r(90000) + 3×r(91000))/4
    Tue 12:00  sell 2 @ 92000                 Q 2, a partial reduction keeps both averages
    Wed 13:00  sell 5 @ 93000                 Q −3, crosses zero: opens at 93000 and r(93000)
    Thu 10:00  buy  3 @ 93500                 Q 0, flat: no average; Fri: no row (OQ-10)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import acceptance_app, expected_rate

TODAY = date(2027, 1, 8)
MON, TUE, WED, THU, FRI = (date(2027, 1, d) for d in (4, 5, 6, 7, 8))
DAYS_TO_MATURITY = {MON: 362, TUE: 361, WED: 360, THU: 359, FRI: 358}


def r(pu: str, on: date) -> Decimal:
    """The execution rate of a trade typed as ``pu`` on ``on`` (spec §4.1, 12 places)."""
    return Decimal(expected_rate(pu, DAYS_TO_MATURITY[on]))


def stored_rate(value: Decimal) -> Decimal:
    with localcontext(prec=34, rounding=ROUND_HALF_UP):
        return value.quantize(Decimal("1E-12"), rounding=ROUND_HALF_UP)


@pytest.fixture
def desk() -> Iterator[Desk]:
    with acceptance_app(TODAY) as (client, database_url):
        yield Desk(client, database_url, TODAY)


@pytest.fixture
def di1f28(desk: Desk) -> str:
    return desk.contract("DI1F28", "2028-01-01")


def _row(desk: Desk, on: date) -> tuple[int, Decimal | None, Decimal | None]:
    row = desk.positions(on)["DI1F28"]
    return row["quantity"], row["average_entry_pu"], row["average_entry_rate"]


def test_increase_partial_reduction_crossing_zero_and_close(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 1, pu="90000", at="10:00")
    desk.trade(di1f28, MON, 3, pu="91000", at="11:00")
    desk.trade(di1f28, TUE, -2, pu="92000", at="12:00")
    desk.trade(di1f28, WED, -5, pu="93000", at="13:00")
    desk.trade(di1f28, THU, 3, pu="93500", at="10:00")
    for day, pu in ((MON, "91000"), (TUE, "92000"), (WED, "93000"), (THU, "93500")):
        desk.price(di1f28, day, pu=pu)

    run = desk.process("ALL", MON, FRI)

    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    assert desk.statuses() == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE, WED, THU, FRI)}
    average_rate = stored_rate((r("90000", MON) + 3 * r("91000", MON)) / 4)
    # Increase: PU and rate each weighted by quantity; the rate is never derived from the PU.
    assert _row(desk, MON) == (4, Decimal("90750"), average_rate)
    # Partial reduction keeps the average of the contracts left.
    assert _row(desk, TUE) == (2, Decimal("90750"), average_rate)
    # Crossing zero closes the long and opens the rest short at the trade's own PU and rate.
    assert _row(desk, WED) == (-3, Decimal("93000"), r("93000", WED))
    # A full close leaves no average, and the flat contract is worth 0.
    assert _row(desk, THU) == (0, None, None)
    assert desk.positions(THU)["DI1F28"]["financial_total"] == 0
    # The day after, the contract is not expected and has no row (OQ-10).
    assert desk.positions(FRI) == {}


def test_the_crossing_trade_stays_one_ledger_row(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, MON, 2, pu="90000", at="10:00")
    crossing = desk.trade(di1f28, MON, -5, pu="91000", at="11:00")
    desk.price(di1f28, MON, pu="91000")

    run = desk.process("ALL", MON, MON)

    assert run["status"] == "COMPLETED", run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED")}
    assert _row(desk, MON) == (-3, Decimal("91000"), r("91000", MON))
    entries = desk.client.get(
        "/api/ledger/entries", params={"start_date": "2027-01-04", "end_date": "2027-01-04"}
    ).json()["items"]
    assert len(entries) == 2  # never split (spec §7.2)
    assert [e["signed_quantity"] for e in entries if e["id"] == crossing["id"]] == [-5]


def test_trades_apply_in_time_order_not_entry_order(desk: Desk, di1f28: str) -> None:
    # Entered last (highest seq) but executed first: (date, time, seq) puts time first (OQ-24).
    #   09:00 buy 2 @ 94000 → long 2 @ 94000
    #   10:00 sell 3 @ 92000 → crosses zero, short 1 @ 92000
    #   11:00 buy 2 @ 90000 → crosses zero, long 1 @ 90000
    # Applied in entry (seq) order it would end long 1 @ 94000.
    desk.trade(di1f28, MON, 2, pu="90000", at="11:00")
    desk.trade(di1f28, MON, -3, pu="92000", at="10:00")
    desk.trade(di1f28, MON, 2, pu="94000", at="09:00")
    desk.price(di1f28, MON, pu="91000")

    run = desk.process("ALL", MON, MON)

    assert run["status"] == "COMPLETED", run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED")}
    assert _row(desk, MON) == (1, Decimal("90000"), r("90000", MON))


def test_same_time_trades_follow_seq(desk: Desk, di1f28: str) -> None:
    #   seq 1 buy 2 @ 90000 → long 2 @ 90000
    #   seq 2 sell 3 @ 92000 → short 1 @ 92000
    #   seq 3 buy 2 @ 94000 → long 1 @ 94000   (in reverse it would end long 1 @ 90000)
    desk.trade(di1f28, MON, 2, pu="90000", at="10:00")
    desk.trade(di1f28, MON, -3, pu="92000", at="10:00")
    desk.trade(di1f28, MON, 2, pu="94000", at="10:00")
    desk.price(di1f28, MON, pu="91000")

    run = desk.process("ALL", MON, MON)

    assert run["status"] == "COMPLETED", run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED")}
    assert _row(desk, MON) == (1, Decimal("94000"), r("94000", MON))


def test_assets_are_independent(desk: Desk, di1f28: str) -> None:
    di1f29 = desk.contract("DI1F29", "2029-01-01")
    desk.trade(di1f28, MON, 2, pu="90000", at="10:00")
    desk.trade(di1f29, MON, -1, pu="82000", at="10:30")
    desk.trade(di1f28, MON, -1, pu="90200", at="11:00")
    desk.price(di1f28, MON, pu="90100")
    desk.price(di1f29, MON, pu="82100")

    run = desk.process("ALL", MON, MON)

    assert run["status"] == "COMPLETED", run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED")}
    rows = desk.positions(MON)
    assert (rows["DI1F28"]["quantity"], rows["DI1F28"]["average_entry_pu"]) == (1, Decimal(90000))
    assert (rows["DI1F29"]["quantity"], rows["DI1F29"]["average_entry_pu"]) == (-1, Decimal(82000))
