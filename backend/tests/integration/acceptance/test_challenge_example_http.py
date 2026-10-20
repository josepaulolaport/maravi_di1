"""The challenge example over HTTP, exactly as written (challenge §3 and §5; spec §15 D2, D3, D4).

Today is 01/01/2027 through the injected clock (D4). The user registers DI1F28 (maturity
01/01/2028, 365 calendar days), deposits 200.000, buys 1 contract at 10% a.a. and enters a 10%
reference price for the same day (D2).

Hand computation (spec §4.1, OQ-3): PU = 100000 / 1.1^(365/365) = 90909.090909… → 90909.0909090909;
the trade's cash effect is −1 × PU, so cash = 200000 − 90909.0909090909 = 109090.9090909091
(109.090,91). Typing that PU back gives (100000 / 90909.0909090909) − 1 = 0.1000000000000001…,
stored at 12 places: 0.100000000000.

Positions, market value and AUM need a processing run (D3): `test_the_challenge_example_end_to_end`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.acceptance.desk import Desk
from tests.integration.acceptance.support import (
    acceptance_app,
    cash_body,
    create_di1_product,
    create_instrument,
    expected_pu,
    price_body,
    trade_body,
)
from tests.support.http import problem_errors

TODAY = date(2027, 1, 1)
PU_AT_10_PERCENT = "90909.0909090909"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with acceptance_app(TODAY) as (client, _):
        yield client


@pytest.fixture
def di1f28(client: TestClient) -> str:
    return create_instrument(client, create_di1_product(client), "DI1F28", "2028-01-01")


def test_the_formula_gives_the_challenge_pu() -> None:
    assert Decimal(expected_pu("0.10", 365)) == Decimal(PU_AT_10_PERCENT)


def test_the_trade_is_priced_at_the_challenge_pu(client: TestClient, di1f28: str) -> None:
    response = client.post(
        "/api/ledger/entries", json=trade_body(di1f28, "2027-01-01", "10:00", 1, rate="0.10")
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["execution_pu"]) == Decimal(PU_AT_10_PERCENT)
    assert Decimal(body["execution_rate"]) == Decimal("0.10")  # typed, kept as typed
    assert body["input_kind"] == "RATE"
    # "Financeiro operação: −90.909,09"
    assert Decimal(body["cash_amount"]) == Decimal("-90909.0909090909")


def test_cash_after_the_deposit_and_the_trade(client: TestClient, di1f28: str) -> None:
    writes = [
        client.post("/api/ledger/entries", json=cash_body("2027-01-01", "09:00", "200000")),
        client.post(
            "/api/ledger/entries", json=trade_body(di1f28, "2027-01-01", "10:00", 1, rate="0.10")
        ),
    ]
    assert [w.status_code for w in writes] == [201, 201], [w.text for w in writes]

    entries = client.get(
        "/api/ledger/entries",
        params={"start_date": "2027-01-01", "end_date": "2027-01-01", "order": "asc"},
    ).json()["items"]

    assert [e["type"] for e in entries] == ["CASH", "TRADE"]
    cash = sum((Decimal(e["cash_amount"]) for e in entries), Decimal(0))
    assert cash == Decimal("109090.9090909091")
    assert cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("109090.91")


def test_the_reference_price_at_10_percent(client: TestClient, di1f28: str) -> None:
    response = client.post(
        "/api/reference-prices", json=price_body(di1f28, "2027-01-01", rate="0.10")
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["source"], Decimal(body["pu"])) == ("MANUAL", Decimal(PU_AT_10_PERCENT))


def test_typing_the_pu_back_recovers_the_rate(client: TestClient, di1f28: str) -> None:
    response = client.post(
        "/api/reference-prices", json=price_body(di1f28, "2027-01-01", pu=PU_AT_10_PERCENT)
    )

    assert response.status_code == 201, response.text
    rate = Decimal(response.json()["rate"])
    assert rate == Decimal("0.1")
    assert rate.as_tuple().exponent == -12  # a calculated rate is stored at 12 places (OQ-3)


def test_before_processing_the_carteira_is_not_processed(client: TestClient, di1f28: str) -> None:
    # D3: the GET only reads published results; nothing is computed on read.
    writes = [
        client.post("/api/ledger/entries", json=cash_body("2027-01-01", "09:00", "200000")),
        client.post(
            "/api/ledger/entries", json=trade_body(di1f28, "2027-01-01", "10:00", 1, rate="0.10")
        ),
        client.post("/api/reference-prices", json=price_body(di1f28, "2027-01-01", rate="0.10")),
    ]
    assert [w.status_code for w in writes] == [201, 201, 201]

    summary = client.get("/api/portfolio/summary", params={"date": "2027-01-01"})

    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert (body["cash"]["status"], body["positions"]["status"]) == (
        "NOT_PROCESSED",
        "NOT_PROCESSED",
    )
    assert body["aum"] is None


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/api/portfolio/summary", {"date": "2027-01-02"}, "date"),
        ("/api/portfolio/positions", {"date": "2027-01-02"}, "date"),
        ("/api/portfolio/pnl", {"start_date": "2026-12-01", "end_date": "2027-01-02"}, "end_date"),
    ],
    ids=["summary", "positions", "pnl"],
)
def test_carteira_reads_after_today_are_refused(
    client: TestClient, path: str, params: dict[str, str], field: str
) -> None:
    response = client.get(path, params=params)

    assert problem_errors(response, 422) == [("FUTURE_DATE", field)]  # OQ-35, spec §13 case 23


def test_the_challenge_example_end_to_end() -> None:
    # D3: the user requests the processing of 01/01/2027; the worker drains it (OQ-45, OQ-46).
    # Hand values (module docstring): cash 109090.9090909091 (109.090,91); DI1F28 1 @
    # 90909.0909090909 (90.909,09) at 10% a.a.; market value 1 × 90909.0909090909;
    # AUM = 109090.9090909091 + 90909.0909090909 = 200000 (200.000,00); Q[D−1] = 0 so position
    # P&L 0 (OQ-4), trades P&L 1 × (PU − PU) = 0.
    with acceptance_app(TODAY) as (client, database_url):
        desk = Desk(client, database_url, TODAY)
        asset = desk.contract("DI1F28", "2028-01-01")
        desk.cash(TODAY, "200000", at="09:00")
        desk.trade(asset, TODAY, 1, rate="0.10", at="10:00")
        desk.price(asset, TODAY, rate="0.10")

        run = desk.process("ALL", TODAY, TODAY)

        assert (run["status"], run["error_code"]) == ("COMPLETED", None), run
        assert desk.statuses() == {TODAY: ("PROCESSED", "PROCESSED")}
        assert desk.cash_balance(TODAY) == Decimal("109090.9090909091")
        row = desk.positions(TODAY)["DI1F28"]
        assert (row["quantity"], row["average_entry_pu"], row["average_entry_rate"]) == (
            1,
            Decimal(PU_AT_10_PERCENT),
            Decimal("0.10"),
        )
        assert (row["reference_source"], row["reference_pu"], row["reference_rate"]) == (
            "MANUAL",
            Decimal(PU_AT_10_PERCENT),
            Decimal("0.10"),
        )
        assert row["financial_total"] == Decimal(PU_AT_10_PERCENT)
        totals = desk.portfolio_pnl(TODAY)
        assert tuple(
            totals[k]
            for k in ("market_value", "position_pnl", "trades_pnl", "daily_pnl", "cumulative_pnl")
        ) == (Decimal(PU_AT_10_PERCENT), Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        assert totals["pnl_status"] == "COMPLETE"
        assert desk.aum(TODAY) == Decimal(200000)
