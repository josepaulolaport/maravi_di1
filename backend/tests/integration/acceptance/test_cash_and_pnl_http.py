"""Spec §13 cases 4, 5, 6 and 13 end to end: cash from trades and movements without P&L in cash;
position, trades and daily P&L per asset, then aggregated; cumulative P&L; deposits and
withdrawals change cash and AUM but never P&L; separate chains and AUM after CASH-only,
POSITIONS-only and ALL runs (spec §7.3, §8.1, §8.2; OQ-4, OQ-21, OQ-38).

Today is Friday 08/01/2027. Monday 04/01/2027, from zero (trades typed as PU):
    DI1F28  buy 1 @ 90000, buy 3 @ 91000, sell 2 @ 92000, sell 5 @ 93000   → Q −3
    DI1F29  buy 2 @ 82000                                                   → Q  2
Tuesday: deposit 50.000 and withdrawal 20.000, no trades.
Reference PUs: DI1F28 92500 (Mon), 92000 (Tue); DI1F29 82100 (Mon), 81900 (Tue).

Hand computation:
    Mon cash      = −(90000 + 273000 − 184000 − 465000) − 164000 = 286000 − 164000 = 122000
    Mon trades    DI1F28 = 1×2500 + 3×1500 − 2×500 − 5×(−500) = 8500;  DI1F29 = 2×100 = 200
    Mon position  0 for both: Q[D−1] = 0 (OQ-4); daily = 8700; cumulative 8700
    Mon MV        = −3×92500 + 2×82100 = −277500 + 164200 = −113300;  AUM = 122000 − 113300 = 8700
    Tue cash      = 122000 + 50000 − 20000 = 152000
    Tue position  DI1F28 = −3×(92000 − 92500) = 1500;  DI1F29 = 2×(81900 − 82100) = −400
    Tue trades    0; daily 1100; cumulative 8700 + 1100 = 9800
    Tue MV        = −3×92000 + 2×81900 = −276000 + 163800 = −112200;  AUM = 152000 − 112200 = 39800
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import acceptance_app

TODAY = date(2027, 1, 8)
MON, TUE = date(2027, 1, 4), date(2027, 1, 5)


@pytest.fixture
def desk() -> Iterator[Desk]:
    with acceptance_app(TODAY) as (client, database_url):
        desk = Desk(client, database_url, TODAY)
        di1f28 = desk.contract("DI1F28", "2028-01-01")
        di1f29 = desk.contract("DI1F29", "2029-01-01")
        desk.trade(di1f28, MON, 1, pu="90000", at="10:00")
        desk.trade(di1f28, MON, 3, pu="91000", at="11:00")
        desk.trade(di1f28, MON, -2, pu="92000", at="12:00")
        desk.trade(di1f28, MON, -5, pu="93000", at="13:00")
        desk.trade(di1f29, MON, 2, pu="82000", at="14:00")
        desk.cash(TUE, "50000", at="09:00")
        desk.cash(TUE, "-20000", at="16:00")
        desk.price(di1f28, MON, pu="92500")
        desk.price(di1f28, TUE, pu="92000")
        desk.price(di1f29, MON, pu="82100")
        desk.price(di1f29, TUE, pu="81900")
        yield desk


def _processed_all(desk: Desk) -> None:
    run = desk.process("ALL", MON, TUE)
    assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED"), TUE: ("PROCESSED", "PROCESSED")}


def test_cash_is_minus_signed_quantity_times_execution_pu_plus_movements(desk: Desk) -> None:
    _processed_all(desk)

    monday, tuesday = desk.summary(MON)["cash"], desk.summary(TUE)["cash"]
    assert (Decimal(monday["balance"]), Decimal(monday["trades_cash_flow"])) == (
        Decimal(122000),
        Decimal(122000),
    )
    assert tuple(
        Decimal(tuesday[k]) for k in ("trades_cash_flow", "deposits", "withdrawals", "balance")
    ) == (Decimal(0), Decimal(50000), Decimal(20000), Decimal(152000))


def test_pnl_per_asset_then_aggregated(desk: Desk) -> None:
    _processed_all(desk)

    monday = desk.positions(MON)
    assert (monday["DI1F28"]["position_pnl"], monday["DI1F28"]["trades_pnl"]) == (0, Decimal(8500))
    assert monday["DI1F28"]["daily_pnl"] == Decimal(8500)
    assert (monday["DI1F29"]["position_pnl"], monday["DI1F29"]["trades_pnl"]) == (0, Decimal(200))
    assert desk.portfolio_pnl(MON) | {"published_at": None} == {
        "status": "PROCESSED",
        "published_at": None,
        "market_value": Decimal(-113300),
        "valuation_status": "COMPLETE",
        "position_pnl": Decimal(0),
        "trades_pnl": Decimal(8700),
        "daily_pnl": Decimal(8700),
        "cumulative_pnl": Decimal(8700),
        "pnl_status": "COMPLETE",
    }

    tuesday = desk.positions(TUE)
    assert (tuesday["DI1F28"]["position_pnl"], tuesday["DI1F28"]["trades_pnl"]) == (
        Decimal(1500),
        0,
    )
    assert (tuesday["DI1F29"]["position_pnl"], tuesday["DI1F29"]["trades_pnl"]) == (
        Decimal(-400),
        0,
    )
    totals = desk.portfolio_pnl(TUE)
    assert (totals["position_pnl"], totals["trades_pnl"], totals["daily_pnl"]) == (
        Decimal(1100),
        Decimal(0),
        Decimal(1100),
    )
    assert totals["cumulative_pnl"] == Decimal(9800)


def test_market_value_is_signed_and_aum_is_cash_plus_market_value(desk: Desk) -> None:
    _processed_all(desk)

    monday = desk.positions(MON)
    # financial_total = Q × reference PU, signed: a short is worth a negative amount (§8.2).
    assert monday["DI1F28"]["financial_total"] == Decimal(-277500)
    assert monday["DI1F29"]["financial_total"] == Decimal(164200)
    assert desk.aum(MON) == Decimal(8700)
    assert desk.portfolio_pnl(TUE)["market_value"] == Decimal(-112200)
    assert desk.aum(TUE) == Decimal(39800)


def test_movements_change_cash_and_aum_but_never_pnl(desk: Desk) -> None:
    _processed_all(desk)

    monday_cash, tuesday_cash = desk.cash_balance(MON), desk.cash_balance(TUE)
    monday_aum, tuesday_aum = desk.aum(MON), desk.aum(TUE)
    assert monday_cash is not None and tuesday_cash is not None
    assert monday_aum is not None and tuesday_aum is not None
    # Tuesday earns 1100 of P&L; cash moves only by the deposit minus the withdrawal ...
    assert desk.portfolio_pnl(TUE)["daily_pnl"] == Decimal(1100)
    assert tuesday_cash - monday_cash == Decimal(30000)
    # ... and AUM moves by both: AUM[D] − AUM[D−1] = daily P&L + deposits − withdrawals.
    assert tuesday_aum - monday_aum == Decimal(1100) + Decimal(30000)


def test_cash_only_then_positions_only(desk: Desk) -> None:
    # Separate chains (OQ-21): CASH needs no positions and no prices; AUM waits for both (OQ-38).
    cash_run = desk.process("CASH", MON, TUE)

    assert (cash_run["status"], cash_run["error_code"]) == ("COMPLETED", None), cash_run
    assert desk.statuses() == {MON: ("PROCESSED", None), TUE: ("PROCESSED", None)}
    assert desk.cash_balance(TUE) == Decimal(152000)
    assert desk.summary(TUE)["positions"]["status"] == "NOT_PROCESSED"
    assert desk.aum(MON) is None
    assert desk.aum(TUE) is None

    positions_run = desk.process("POSITIONS", MON, TUE)

    assert (positions_run["status"], positions_run["error_code"]) == ("COMPLETED", None)
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED"), TUE: ("PROCESSED", "PROCESSED")}
    # The scope that publishes recomputes AUM from the other chain's published cash (OQ-21).
    assert desk.aum(MON) == Decimal(8700)
    assert desk.aum(TUE) == Decimal(39800)


def test_positions_only_then_cash_only(desk: Desk) -> None:
    positions_run = desk.process("POSITIONS", MON, TUE)

    assert (positions_run["status"], positions_run["error_code"]) == ("COMPLETED", None)
    assert desk.statuses() == {MON: (None, "PROCESSED"), TUE: (None, "PROCESSED")}
    assert desk.portfolio_pnl(TUE)["market_value"] == Decimal(-112200)
    assert desk.summary(TUE)["cash"]["status"] == "NOT_PROCESSED"
    assert desk.aum(TUE) is None

    cash_run = desk.process("CASH", MON, TUE)

    assert (cash_run["status"], cash_run["error_code"]) == ("COMPLETED", None), cash_run
    assert desk.statuses() == {MON: ("PROCESSED", "PROCESSED"), TUE: ("PROCESSED", "PROCESSED")}
    assert desk.aum(MON) == Decimal(8700)
    assert desk.aum(TUE) == Decimal(39800)
