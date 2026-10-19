"""Ledger entries over HTTP (spec §6, §13 cases 1, 9, 16, 22; OQ-1, OQ-3, OQ-13, OQ-14, OQ-24,
OQ-31, OQ-32, OQ-37).

Today is Friday 08/01/2027. DI1F28 matures on 01/01/2028; DI1F27 matured on Monday 04/01/2027.
Expected PUs are spec §4.1's formula (``expected_pu``): from 06/01/2027 to 01/01/2028 there are
360 calendar days.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.acceptance.support import (
    acceptance_app,
    cash_body,
    create_di1_product,
    create_instrument,
    derived_rows,
    expected_pu,
    expected_rate,
    problem,
    sql,
    trade_body,
)

TODAY = date(2027, 1, 8)
WEEK = {"start_date": "2027-01-01", "end_date": "2027-01-08"}


@pytest.fixture
def app() -> Iterator[tuple[TestClient, str]]:
    with acceptance_app(TODAY) as app:
        yield app


@pytest.fixture
def client(app: tuple[TestClient, str]) -> TestClient:
    return app[0]


@pytest.fixture
def contracts(client: TestClient) -> dict[str, str]:
    product_id = create_di1_product(client)
    return {
        "DI1F28": create_instrument(client, product_id, "DI1F28", "2028-01-01"),
        "DI1F27": create_instrument(client, product_id, "DI1F27", "2027-01-04"),
    }


def _post(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/ledger/entries", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _listed(client: TestClient, **params: Any) -> list[str]:
    response = client.get("/api/ledger/entries", params={**WEEK, **params})
    assert response.status_code == 200, response.text
    return [e["id"] for e in response.json()["items"]]


def test_trade_typed_as_rate_or_pu_stores_both(
    client: TestClient, contracts: dict[str, str]
) -> None:
    pu = expected_pu("0.105", 360)

    by_rate = _post(client, trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 5, rate="0.105"))
    by_pu = _post(client, trade_body(contracts["DI1F28"], "2027-01-06", "11:00", -2, pu=pu))

    assert (by_rate["execution_pu"], by_rate["execution_rate"]) == (pu, "0.105")
    assert (by_pu["execution_pu"], by_pu["execution_rate"]) == (pu, expected_rate(pu, 360))
    # The cash effect is −signed quantity × execution PU (spec §7.3): a sale brings cash in.
    assert Decimal(by_rate["cash_amount"]) == -5 * Decimal(pu)
    assert Decimal(by_pu["cash_amount"]) == 2 * Decimal(pu)
    # Read back from storage: the typed value as typed, the computed one as stored (OQ-3).
    stored = client.get("/api/ledger/entries", params={**WEEK, "order": "asc"}).json()["items"]
    assert [(e["input_kind"], e["execution_pu"], e["execution_rate"]) for e in stored] == [
        ("RATE", pu, "0.105"),
        ("PU", pu, expected_rate(pu, 360)),
    ]


def test_the_day_before_maturity_is_one_calendar_day(
    client: TestClient, contracts: dict[str, str]
) -> None:
    # Near maturity (spec §13 case 1): Sunday 03/01/2027 is 1 calendar day before 04/01.
    near = _post(client, trade_body(contracts["DI1F27"], "2027-01-03", "10:00", 1, rate="0.10"))

    assert near["execution_pu"] == expected_pu("0.10", 1)


def test_a_rate_with_12_places_is_accepted(client: TestClient, contracts: dict[str, str]) -> None:
    rate = "0.100000000001"

    entry = _post(client, trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, rate=rate))

    assert (entry["execution_rate"], entry["execution_pu"]) == (rate, expected_pu(rate, 360))


def test_trades_and_cash_share_one_order(client: TestClient, contracts: dict[str, str]) -> None:
    # Same date, both types, ordered by (date, time, seq) across types (OQ-24).
    trade_ten = _post(
        client, trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, rate="0.10")
    )
    cash_nine = _post(client, cash_body("2027-01-06", "09:00", "1000"))
    cash_ten = _post(client, cash_body("2027-01-06", "10:00", "-500"))
    earlier_day = _post(client, cash_body("2027-01-05", "18:00", "2000"))

    ascending = _listed(client, order="asc")

    assert ascending == [earlier_day["id"], cash_nine["id"], trade_ten["id"], cash_ten["id"]]
    assert _listed(client, order="desc") == ascending[::-1]
    assert trade_ten["seq"] < cash_ten["seq"]  # same time: the later entry has the higher seq


def test_entries_page_by_cursor(client: TestClient) -> None:
    ids = [
        _post(client, cash_body("2027-01-0" + str(day), "09:00", "100"))["id"] for day in (2, 3, 4)
    ]

    first = client.get("/api/ledger/entries", params={**WEEK, "order": "asc", "limit": 2}).json()
    second = client.get(
        "/api/ledger/entries",
        params={**WEEK, "order": "asc", "limit": 2, "cursor": first["next_cursor"]},
    ).json()

    assert [e["id"] for e in first["items"]] == ids[:2]
    assert first["next_cursor"] is not None
    assert [e["id"] for e in second["items"]] == ids[2:]
    assert second["next_cursor"] is None


@pytest.mark.parametrize("limit", [0, 201])
@pytest.mark.parametrize(
    ("path", "params"),
    [("/api/ledger/entries", WEEK), ("/api/processing/requests", {})],
    ids=["ledger", "processing"],
)
def test_a_page_limit_outside_1_to_200_is_refused(
    client: TestClient, path: str, params: dict[str, str], limit: int
) -> None:
    response = client.get(path, params={**params, "limit": limit})

    assert problem(response, 422) == [("VALIDATION_ERROR", "limit")]  # OQ-37


def test_mixed_batch_delete_is_hard_and_all_or_nothing(
    app: tuple[TestClient, str], contracts: dict[str, str]
) -> None:
    client, database_url = app
    trade = _post(client, trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, rate="0.10"))
    cash = _post(client, cash_body("2027-01-06", "09:00", "1000"))
    kept = _post(client, cash_body("2027-01-07", "09:00", "50"))
    unknown = "00000000-0000-0000-0000-000000000000"

    refused = client.post("/api/ledger/entries/deletions", json={"ids": [trade["id"], unknown]})
    assert problem(refused, 404) == [("NOT_FOUND", None)]
    assert sorted(_listed(client)) == sorted([trade["id"], cash["id"], kept["id"]])

    deleted = client.post(
        "/api/ledger/entries/deletions", json={"ids": [trade["id"], cash["id"], cash["id"]]}
    )
    assert deleted.status_code == 204, deleted.text
    assert _listed(client) == [kept["id"]]
    # A hard delete (OQ-32): the rows are gone from ledger.entries, not flagged.
    assert sql(database_url, "SELECT count(*) FROM ledger.entries") == [(1,)]

    again = client.post("/api/ledger/entries/deletions", json={"ids": [cash["id"]]})
    assert problem(again, 404) == [("NOT_FOUND", None)]


def test_an_empty_deletion_is_refused(client: TestClient) -> None:
    response = client.post("/api/ledger/entries/deletions", json={"ids": []})

    assert problem(response, 422) == [("VALIDATION_ERROR", "ids")]


def test_a_write_saves_only_the_fact(
    app: tuple[TestClient, str], contracts: dict[str, str]
) -> None:
    # OQ-31: no date is marked, no job is created, nothing is published.
    client, database_url = app
    entry = _post(client, trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, rate="0.10"))
    deleted = client.post("/api/ledger/entries/deletions", json={"ids": [entry["id"]]})
    _post(client, cash_body("2027-01-06", "09:00", "1000"))

    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/processing/requests").json()["items"] == []
    assert set(derived_rows(database_url).values()) == {0}


def test_weekends_and_holidays_are_accepted(client: TestClient, contracts: dict[str, str]) -> None:
    # Saturday 02/01/2027 and the 01/01 holiday (OQ-7).
    _post(client, cash_body("2027-01-01", "09:00", "1000"))
    _post(client, trade_body(contracts["DI1F28"], "2027-01-02", "10:00", 1, rate="0.10"))


def test_an_entry_after_today_is_refused(client: TestClient, contracts: dict[str, str]) -> None:
    cash = client.post("/api/ledger/entries", json=cash_body("2027-01-09", "09:00", "1000"))
    trade = client.post(
        "/api/ledger/entries",
        json=trade_body(contracts["DI1F28"], "2027-01-09", "10:00", 1, rate="0.10"),
    )

    assert problem(cash, 422) == [("FUTURE_DATE", "date")]
    assert problem(trade, 422) == [("FUTURE_DATE", "date")]


def test_maturity_date_takes_a_typed_pu_and_stores_rate_zero(
    client: TestClient, contracts: dict[str, str]
) -> None:
    on_maturity = _post(
        client, trade_body(contracts["DI1F27"], "2027-01-04", "10:00", -1, pu="100000")
    )
    typed_rate = client.post(
        "/api/ledger/entries",
        json=trade_body(contracts["DI1F27"], "2027-01-04", "11:00", 1, rate="0.10"),
    )

    assert on_maturity["execution_pu"] == "100000"
    assert Decimal(on_maturity["execution_rate"]) == 0
    assert problem(typed_rate, 422) == [("VALIDATION_ERROR", "execution_rate")]


def test_a_trade_after_maturity_is_refused(client: TestClient, contracts: dict[str, str]) -> None:
    response = client.post(
        "/api/ledger/entries",
        json=trade_body(contracts["DI1F27"], "2027-01-05", "10:00", 1, pu="100000"),
    )

    assert problem(response, 422) == [("CONTRACT_MATURED", "date")]


def test_too_many_decimals_are_refused_never_rounded(
    client: TestClient, contracts: dict[str, str]
) -> None:
    # OQ-3: a typed rate takes at most 12 places, a typed PU at most 10.
    rate = client.post(
        "/api/ledger/entries",
        json=trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, rate="0.1000000000001"),
    )
    pu = client.post(
        "/api/ledger/entries",
        json=trade_body(contracts["DI1F28"], "2027-01-06", "10:00", 1, pu="90000.00000000001"),
    )

    assert problem(rate, 422) == [("VALIDATION_ERROR", "execution_rate")]
    assert problem(pu, 422) == [("VALIDATION_ERROR", "execution_pu")]
