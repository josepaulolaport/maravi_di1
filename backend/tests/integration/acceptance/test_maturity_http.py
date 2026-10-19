"""Maturity end to end (spec §7.4, §13 case 7; OQ-1, OQ-37): no automatic settlement; the user
closes with a normal trade on the maturity date (PU typed, rate 0) and enters the maturity-day
reference price; after maturity the reference PU is 0 by definition, so an open position loses
Q × (0 − PU_maturity), and the Pendência "contrato vencido com posição aberta" is raised once per
asset. Pricing's own maturity rules (rate 0, a typed rate or a later date refused) are in
`test_ledger_http.py` and `test_reference_prices_http.py`.

Today is Friday 08/01/2027; DI1F27 matures on Wednesday 06/01/2027.
    Tue 05/01  buy 2 @ 99980, reference 99985   trades 2 × 5 = 10; cash −199960; AUM 10
    Wed 06/01  sell 1 @ 100000 (maturity), reference 100000 (typed by the user)
               position 2 × (100000 − 99985) = 30; trades −1 × 0 = 0; cumulative 40
               cash −199960 + 100000 = −99960; market value 1 × 100000; AUM 40
    Thu 07/01  1 still open, reference PU 0 by definition
               position 1 × (0 − 100000) = −100000; cumulative −99960; market value 0;
               AUM −99960; Pendência: expired with an open position
    Fri 08/01  position 1 × (0 − 0) = 0; cumulative −99960
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import acceptance_app

TODAY = date(2027, 1, 8)
TUE, MATURITY, THU, FRI = (date(2027, 1, d) for d in (5, 6, 7, 8))
EXPIRED = "EXPIRED_OPEN_POSITION"
MISSING = "MISSING_REFERENCE_PRICE"


@pytest.fixture
def desk() -> Iterator[Desk]:
    with acceptance_app(TODAY) as (client, database_url):
        yield Desk(client, database_url, TODAY)


@pytest.fixture
def di1f27(desk: Desk) -> str:
    asset = desk.contract("DI1F27", "2027-01-06")
    desk.trade(asset, TUE, 2, pu="99980")
    closing = desk.trade(asset, MATURITY, -1, pu="100000")
    assert Decimal(closing["execution_rate"]) == 0  # the maturity date's rate is 0 (OQ-1)
    desk.price(asset, TUE, pu="99985")
    return asset


def test_close_on_the_maturity_date_and_leave_one_open(desk: Desk, di1f27: str) -> None:
    desk.price(di1f27, MATURITY, pu="100000")

    run = desk.process("ALL", TUE, FRI)

    # The open position after maturity is a pendência, not a failure.
    assert (run["status"], run["error_code"]) == ("COMPLETED_WITH_ISSUES", None), run
    assert desk.statuses() == {
        TUE: ("PROCESSED", "PROCESSED"),
        MATURITY: ("PROCESSED", "PROCESSED"),
        THU: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
        FRI: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
    }
    assert desk.issues() == [(EXPIRED, "DI1F27", THU, None)]  # once per asset (OQ-37)

    assert desk.portfolio_pnl(TUE)["cumulative_pnl"] == Decimal(10)
    assert desk.aum(TUE) == Decimal(10)

    maturity = desk.positions(MATURITY)["DI1F27"]
    assert maturity["quantity"] == 1
    assert (maturity["position_pnl"], maturity["trades_pnl"]) == (Decimal(30), Decimal(0))
    assert maturity["financial_total"] == Decimal(100000)
    assert desk.portfolio_pnl(MATURITY)["cumulative_pnl"] == Decimal(40)
    assert desk.cash_balance(MATURITY) == Decimal(-99960)
    assert desk.aum(MATURITY) == Decimal(40)


def test_after_maturity_the_value_is_zero_and_the_open_position_loses_its_pu(
    desk: Desk, di1f27: str
) -> None:
    desk.price(di1f27, MATURITY, pu="100000")
    run = desk.process("ALL", TUE, FRI)
    assert run["status"] == "COMPLETED_WITH_ISSUES", run
    assert (desk.statuses()[THU], desk.statuses()[FRI]) == (
        ("PROCESSED", "PROCESSED_WITH_ISSUES"),
    ) * 2

    thursday = desk.positions(THU)["DI1F27"]
    # Still expected (Q[D−1] = 1); valued at PU 0, which is a price, not a missing one.
    assert thursday["quantity"] == 1
    assert (thursday["financial_total"], thursday["valuation_status"]) == (Decimal(0), "COMPLETE")
    assert thursday["position_pnl"] == Decimal(-100000)
    totals = desk.portfolio_pnl(THU)
    assert (totals["daily_pnl"], totals["cumulative_pnl"]) == (Decimal(-100000), Decimal(-99960))
    assert desk.aum(THU) == Decimal(-99960)

    friday = desk.positions(FRI)["DI1F27"]
    assert friday["position_pnl"] == Decimal(0)
    totals = desk.portfolio_pnl(FRI)
    assert (totals["cumulative_pnl"], totals["pnl_status"]) == (Decimal(-99960), "COMPLETE")


def test_without_the_maturity_day_price_the_figures_are_null(desk: Desk, di1f27: str) -> None:
    # The maturity-day price is the user's: none is assumed (OQ-1).
    run = desk.process("ALL", TUE, THU)

    assert (run["status"], run["error_code"]) == ("COMPLETED_WITH_ISSUES", None), run
    assert desk.statuses() == {
        TUE: ("PROCESSED", "PROCESSED"),
        MATURITY: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
        THU: ("PROCESSED", "PROCESSED_WITH_ISSUES"),
    }
    maturity = desk.positions(MATURITY)["DI1F27"]
    assert (maturity["financial_total"], maturity["position_pnl"]) == (None, None)
    assert desk.portfolio_pnl(MATURITY)["daily_pnl"] is None
    # Thursday is worth 0, but its position P&L needs the maturity-day PU as D−1's price.
    thursday = desk.positions(THU)["DI1F27"]
    assert (thursday["financial_total"], thursday["position_pnl"]) == (Decimal(0), None)
    assert desk.portfolio_pnl(THU)["cumulative_pnl"] is None
    # The maturity-day price is needed by both dates: one pendência for it (OQ-37), plus one
    # for the open position after maturity.
    assert desk.issues() == [
        (EXPIRED, "DI1F27", THU, None),
        (MISSING, "DI1F27", MATURITY, MATURITY),
    ]
