"""Spec §13 cases 7, 8, 15, 21 and 27 end to end: every calendar day, weekends included; a
missing exact-date price gives null, never zero and never carried forward; partial P&L never
looks complete; a day with no expected asset; one pendência per (asset, required price date);
the P&L chart over days without P&L (spec §5, §7.1, §8.1, §8.3; OQ-4, OQ-10, OQ-22, OQ-37,
OQ-38, OQ-41). A missing price is not a failure: the run ends ``COMPLETED_WITH_ISSUES`` and the
positions chain of the affected date ``PROCESSED_WITH_ISSUES`` (spec §10).

Today is Wednesday 13/01/2027; DI1F28 matures on 01/01/2028, DI1F29 on 01/01/2029. Trades and
prices are typed as PU.

Weekend scenario: Friday 08/01 buy 2 @ 90000; reference 90100 Friday, none Saturday, 90300
Sunday, 90400 Monday.
    Fri  trades 2 × (90100 − 90000) = 200; cumulative 200; cash −180000; AUM −180000 + 180200 = 200
    Sat  no price: quantity 2, average 90000 and cash −180000 still computed; market value,
         AUM, position P&L, daily and cumulative P&L null (no carry-forward of 90100)
    Sun  Saturday's price is D−1's: position P&L null; Sunday's own price values the position,
         2 × 90300 = 180600, AUM −180000 + 180600 = 600
    Mon  complete on its own: 2 × (90400 − 90300) = 200; cumulative stays null from Saturday
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import acceptance_app

TODAY = date(2027, 1, 13)
FRI, SAT, SUN, MON, TUE, WED = (date(2027, 1, d) for d in (8, 9, 10, 11, 12, 13))
MISSING = "MISSING_REFERENCE_PRICE"


@pytest.fixture
def desk() -> Iterator[Desk]:
    with acceptance_app(TODAY) as (client, database_url):
        yield Desk(client, database_url, TODAY)


@pytest.fixture
def di1f28(desk: Desk) -> str:
    return desk.contract("DI1F28", "2028-01-01")


def _weekend(desk: Desk, asset: str, *, prices: dict[date, str]) -> None:
    desk.trade(asset, FRI, 2, pu="90000")
    for day, pu in prices.items():
        desk.price(asset, day, pu=pu)


WEEKEND_PRICES = {FRI: "90100", SUN: "90300", MON: "90400"}


def test_a_missing_price_ends_with_issues_and_marks_only_its_dates(desk: Desk, di1f28: str) -> None:
    _weekend(desk, di1f28, prices=WEEKEND_PRICES)

    run = desk.process("ALL", FRI, MON)

    # Every calendar day is processed, weekends included; a missing price is not an error.
    assert (run["status"], run["error_code"], run["failed_date"]) == (
        "COMPLETED_WITH_ISSUES",
        None,
        None,
    ), run
    assert desk.statuses() == {
        FRI: ("PROCESSED", "PROCESSED"),
        SAT: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
        SUN: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
        MON: ("PROCESSED", "PROCESSED"),
    }
    # Saturday's price is required by Saturday (D) and Sunday (D−1): one pendência (OQ-37).
    assert desk.issues() == [(MISSING, "DI1F28", SAT, SAT)]


def test_no_price_on_saturday_leaves_dependent_figures_null(desk: Desk, di1f28: str) -> None:
    _weekend(desk, di1f28, prices=WEEKEND_PRICES)
    run = desk.process("ALL", FRI, MON)
    assert run["status"] == "COMPLETED_WITH_ISSUES", run
    assert desk.statuses()[SAT] == ("PROCESSED", "PROCESSED_WITH_ISSUES")

    row = desk.positions(SAT)["DI1F28"]
    totals = desk.portfolio_pnl(SAT)

    # Quantity, average cost and cash are still computed (§8.3).
    assert (row["quantity"], row["average_entry_pu"]) == (2, Decimal(90000))
    assert desk.cash_balance(SAT) == Decimal(-180000)
    # No carry-forward of Friday's 90100: null, never zero (§5, §8.3).
    assert (row["reference_pu"], row["financial_total"], row["position_pnl"]) == (None, None, None)
    assert row["valuation_status"] == "MISSING"
    assert (totals["market_value"], totals["daily_pnl"], totals["cumulative_pnl"]) == (
        None,
        None,
        None,
    )
    assert totals["pnl_status"] == "MISSING"
    assert desk.aum(SAT) is None


def test_missing_previous_price_blocks_position_pnl_but_not_market_value(
    desk: Desk, di1f28: str
) -> None:
    _weekend(desk, di1f28, prices=WEEKEND_PRICES)
    run = desk.process("ALL", FRI, MON)
    assert run["status"] == "COMPLETED_WITH_ISSUES", run
    assert desk.statuses()[SUN] == ("PROCESSED", "PROCESSED_WITH_ISSUES")

    row = desk.positions(SUN)["DI1F28"]

    assert row["position_pnl"] is None
    assert row["financial_total"] == Decimal(180600)
    assert desk.aum(SUN) == Decimal(600)
    assert desk.portfolio_pnl(SUN)["daily_pnl"] is None


def test_cumulative_pnl_stays_unavailable_from_the_first_gap(desk: Desk, di1f28: str) -> None:
    _weekend(desk, di1f28, prices=WEEKEND_PRICES)
    run = desk.process("ALL", FRI, MON)
    assert run["status"] == "COMPLETED_WITH_ISSUES", run
    assert (desk.statuses()[FRI], desk.statuses()[MON]) == (("PROCESSED", "PROCESSED"),) * 2

    friday, monday = desk.portfolio_pnl(FRI), desk.portfolio_pnl(MON)

    assert (friday["daily_pnl"], friday["cumulative_pnl"]) == (Decimal(200), Decimal(200))
    assert desk.aum(FRI) == Decimal(200)
    # Monday is complete on its own, but the cumulative chain broke on Saturday (§8.3).
    assert (monday["daily_pnl"], monday["pnl_status"]) == (Decimal(200), "COMPLETE")
    assert monday["cumulative_pnl"] is None


def test_both_prices_missing(desk: Desk, di1f28: str) -> None:
    # Only Friday's price: Sunday misses both D (Sunday) and D−1 (Saturday).
    _weekend(desk, di1f28, prices={FRI: "90100"})

    run = desk.process("ALL", FRI, SUN)

    assert (run["status"], run["error_code"]) == ("COMPLETED_WITH_ISSUES", None), run
    assert desk.statuses() == {
        FRI: ("PROCESSED", "PROCESSED"),
        SAT: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
        SUN: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
    }
    row = desk.positions(SUN)["DI1F28"]
    assert (row["quantity"], row["position_pnl"], row["financial_total"]) == (2, None, None)
    assert desk.cash_balance(SUN) == Decimal(-180000)
    assert desk.aum(SUN) is None
    assert desk.portfolio_pnl(SUN)["daily_pnl"] is None
    # One pendência per (asset, required price date), each with its earliest affected date.
    assert desk.issues() == [(MISSING, "DI1F28", SAT, SAT), (MISSING, "DI1F28", SUN, SUN)]


def test_partial_pnl_never_looks_like_a_complete_portfolio_total(desk: Desk, di1f28: str) -> None:
    # Case 8: two expected assets, only DI1F28 priced on the day.
    di1f29 = desk.contract("DI1F29", "2029-01-01")
    desk.trade(di1f28, FRI, 1, pu="90000", at="10:00")
    desk.trade(di1f29, FRI, 1, pu="82000", at="11:00")
    desk.price(di1f28, FRI, pu="90100")

    run = desk.process("ALL", FRI, FRI)

    assert (run["status"], run["error_code"]) == ("COMPLETED_WITH_ISSUES", None), run
    assert desk.statuses() == {FRI: ("PROCESSED", "PROCESSED_WITH_ISSUES")}
    rows = desk.positions(FRI)
    assert (rows["DI1F28"]["daily_pnl"], rows["DI1F28"]["pnl_status"]) == (Decimal(100), "COMPLETE")
    assert rows["DI1F29"]["trades_pnl"] is None
    totals = desk.portfolio_pnl(FRI)
    assert (totals["trades_pnl"], totals["daily_pnl"]) == (None, None)  # not 100
    assert (totals["market_value"], totals["valuation_status"]) == (None, "MISSING")  # not 90100
    assert totals["pnl_status"] == "MISSING"
    assert desk.aum(FRI) is None
    assert desk.issues() == [(MISSING, "DI1F29", FRI, FRI)]


def test_same_day_round_trip_needs_the_day_price(desk: Desk, di1f28: str) -> None:
    desk.trade(di1f28, FRI, 1, pu="90000", at="10:00")
    desk.trade(di1f28, FRI, -1, pu="90300", at="11:00")

    without_price = desk.process("ALL", FRI, FRI)

    assert without_price["status"] == "COMPLETED_WITH_ISSUES", without_price
    assert desk.statuses() == {FRI: ("PROCESSED", "PROCESSED_WITH_ISSUES")}
    row = desk.positions(FRI)["DI1F28"]
    # Flat at the close: still expected (it traded), worth 0 without a price ...
    assert (row["quantity"], row["financial_total"], row["valuation_status"]) == (
        0,
        Decimal(0),
        "NOT_REQUIRED",
    )
    assert desk.aum(FRI) == Decimal(300)  # cash 90300 − 90000
    # ... but its trades P&L needs the day's price (§8.3).
    without = desk.portfolio_pnl(FRI)
    assert (without["trades_pnl"], without["pnl_status"]) == (None, "MISSING")
    assert desk.issues() == [(MISSING, "DI1F28", FRI, FRI)]

    desk.price(di1f28, FRI, pu="90200")
    with_price = desk.process("ALL", FRI, FRI)

    assert (with_price["status"], with_price["error_code"]) == ("COMPLETED", None), with_price
    assert desk.statuses() == {FRI: ("PROCESSED", "PROCESSED")}
    # (90200 − 90000) − (90200 − 90300) = 300; the pendência is replaced by none.
    totals = desk.portfolio_pnl(FRI)
    assert (totals["trades_pnl"], totals["daily_pnl"]) == (Decimal(300), Decimal(300))
    assert desk.issues() == []


def _flat_from_tuesday(desk: Desk, asset: str) -> None:
    # Monday buy 1 @ 90000 (ref 90100); Tuesday sell 1 @ 90250 (ref 90200); Wednesday nothing.
    desk.trade(asset, MON, 1, pu="90000")
    desk.trade(asset, TUE, -1, pu="90250")
    desk.price(asset, MON, pu="90100")
    desk.price(asset, TUE, pu="90200")


def test_day_without_expected_asset(desk: Desk, di1f28: str) -> None:
    # Case 15 (OQ-22): Tuesday position 1 × 100 + trades −1 × (90200 − 90250) = 150;
    # cumulative 100 + 150 = 250; Wednesday has no expected asset; cash 90250 − 90000 = 250.
    _flat_from_tuesday(desk, di1f28)

    run = desk.process("ALL", MON, WED)

    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    assert desk.statuses() == {d: ("PROCESSED", "PROCESSED") for d in (MON, TUE, WED)}
    tuesday = desk.portfolio_pnl(TUE)
    assert (tuesday["daily_pnl"], tuesday["cumulative_pnl"]) == (Decimal(150), Decimal(250))
    assert desk.positions(WED) == {}
    wednesday = desk.portfolio_pnl(WED)
    assert (wednesday["position_pnl"], wednesday["trades_pnl"], wednesday["daily_pnl"]) == (
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )
    assert (wednesday["pnl_status"], wednesday["cumulative_pnl"]) == ("COMPLETE", Decimal(250))
    assert wednesday["market_value"] == 0
    assert desk.aum(WED) == desk.cash_balance(WED) == Decimal(250)


def test_day_without_expected_asset_and_no_cash_chain_has_no_aum(desk: Desk, di1f28: str) -> None:
    # Case 15 with only the positions chain processed: AUM is null, not the market value (OQ-38).
    _flat_from_tuesday(desk, di1f28)

    run = desk.process("POSITIONS", MON, WED)

    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    assert desk.statuses() == {d: (None, "PROCESSED") for d in (MON, TUE, WED)}
    assert desk.portfolio_pnl(WED)["daily_pnl"] == Decimal(0)
    assert desk.aum(WED) is None


def test_the_pnl_chart_adds_zero_for_days_without_pnl(desk: Desk, di1f28: str) -> None:
    # Case 27 (OQ-41): a 30-day chart, 15/12/2026 to 13/01/2027, starting before the first
    # processed day. The weekend run gives daily 200 (Fri), null (Sat, Sun), 200 (Mon); Tuesday is
    # never processed; Wednesday's POSITIONS run fails (D−1 has no status after earlier ones:
    # a gap, OQ-37 item 4). The line: 0 up to Thursday, 200, 200, 200, 400, 400 (Tue), 400 (Wed).
    _weekend(desk, di1f28, prices=WEEKEND_PRICES)
    weekend = desk.process("ALL", FRI, MON)
    assert weekend["status"] == "COMPLETED_WITH_ISSUES", weekend
    failed = desk.process("POSITIONS", WED, WED)
    assert (failed["status"], failed["error_code"]) == (
        "FAILED",
        "POSITIONS_PREDECESSOR_MISSING",
    ), failed
    assert desk.statuses()[WED] == (None, "FAILED")
    start = date(2026, 12, 15)

    points = desk.pnl_series(start, WED)

    assert [date.fromisoformat(p["date"]) for p in points] == [
        start + timedelta(days=n) for n in range(30)
    ]
    before = points[:24]  # 15/12 to 07/01
    assert {p["status"] for p in before} == {"NOT_PROCESSED"}
    assert {p["range_cumulative_pnl"] for p in before} == {Decimal(0)}
    assert all(p["daily_pnl"] is None for p in before)
    by_day = {date.fromisoformat(p["date"]): p for p in points}
    assert [
        (by_day[d]["status"], by_day[d]["daily_pnl"], by_day[d]["range_cumulative_pnl"])
        for d in (FRI, SAT, SUN, MON, TUE, WED)
    ] == [
        ("PROCESSED", Decimal(200), Decimal(200)),
        ("PROCESSED_WITH_ISSUES", None, Decimal(200)),
        ("PROCESSED_WITH_ISSUES", None, Decimal(200)),
        ("PROCESSED", Decimal(200), Decimal(400)),
        ("NOT_PROCESSED", None, Decimal(400)),
        ("FAILED", None, Decimal(400)),
    ]
    # The stored cumulative P&L stays unavailable from the first gap, on the summary (OQ-49).
    assert [desk.portfolio_pnl(d)["cumulative_pnl"] for d in (FRI, SAT, SUN, MON)] == [
        Decimal(200),
        None,
        None,
        None,
    ]
