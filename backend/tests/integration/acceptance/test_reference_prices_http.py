"""Reference prices over HTTP (spec §5, §7.4, §13 cases 1, 7, 9 and 17; OQ-1, OQ-25, OQ-26,
OQ-31). A write dated after today and reads after today (OQ-42) are in
``tests/integration/prices/test_reference_prices_http.py``.

Today is Friday 08/01/2027. DI1F28 matures on 01/01/2028 (360 calendar days from 06/01/2027);
DI1F27 matured on Monday 04/01/2027. B3 prices have no HTTP route yet (a future import), so the
B3 row is inserted directly, as that import would.
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
    create_di1_product,
    create_instrument,
    derived_rows,
    expected_pu,
    price_body,
    problem,
    sql,
)

TODAY = date(2027, 1, 8)
DAY = "2027-01-06"


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


def _set(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/reference-prices", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _days(client: TestClient, asset_id: str, start: str, end: str) -> list[dict[str, Any]]:
    response = client.get(
        "/api/reference-prices", params={"asset_id": asset_id, "start_date": start, "end_date": end}
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _insert_b3(database_url: str, asset_id: str, on: str, rate: str, pu: str) -> None:
    sql(
        database_url,
        "INSERT INTO prices.reference_prices"
        " (asset_id, reference_date, source, input_kind, pu, rate)"
        " VALUES (%s, %s, 'B3', 'RATE', %s, %s)",
        (asset_id, on, pu, rate),
    )


def test_manual_wins_over_b3_and_removing_it_lets_b3_prevail(
    app: tuple[TestClient, str], contracts: dict[str, str]
) -> None:
    client, database_url = app
    asset = contracts["DI1F28"]
    b3_pu = expected_pu("0.11", 360)
    _insert_b3(database_url, asset, DAY, "0.11", b3_pu)

    manual = _set(client, price_body(asset, DAY, rate="0.10"))
    [day] = _days(client, asset, DAY, DAY)

    assert (day["preferred"]["source"], Decimal(day["preferred"]["pu"])) == (
        "MANUAL",
        Decimal(expected_pu("0.10", 360)),
    )
    assert sorted(s["source"] for s in day["sources"]) == ["B3", "MANUAL"]

    removed = client.delete(f"/api/reference-prices/{manual['id']}")
    [after] = _days(client, asset, DAY, DAY)

    assert removed.status_code == 204
    assert (after["preferred"]["source"], Decimal(after["preferred"]["pu"])) == (
        "B3",
        Decimal(b3_pu),
    )
    assert [s["source"] for s in after["sources"]] == ["B3"]


def test_a_correction_replaces_the_price_of_its_source(
    app: tuple[TestClient, str], contracts: dict[str, str]
) -> None:
    # One row per (asset, date, source), no revisions (OQ-25, OQ-26 item 7).
    client, database_url = app
    asset = contracts["DI1F28"]
    first = _set(client, price_body(asset, DAY, rate="0.10"))

    corrected = _set(client, price_body(asset, DAY, rate="0.12"))
    [day] = _days(client, asset, DAY, DAY)

    assert corrected["id"] != first["id"]
    assert Decimal(day["preferred"]["pu"]) == Decimal(expected_pu("0.12", 360))
    assert sql(database_url, "SELECT count(*) FROM prices.reference_prices") == [(1,)]


def test_exact_date_only_without_carry_forward(
    client: TestClient, contracts: dict[str, str]
) -> None:
    asset = contracts["DI1F28"]
    _set(client, price_body(asset, DAY, rate="0.10"))

    days = _days(client, asset, "2027-01-05", "2027-01-08")

    # Only 06/01 has a price; 07/01 and 08/01 do not inherit it (spec §5).
    assert [d["reference_date"] for d in days] == [DAY]


def test_maturity_day_price_is_a_typed_pu_with_rate_zero(
    client: TestClient, contracts: dict[str, str]
) -> None:
    asset = contracts["DI1F27"]

    on_maturity = _set(client, price_body(asset, "2027-01-04", pu="100000"))
    typed_rate = client.post(
        "/api/reference-prices", json=price_body(asset, "2027-01-04", rate="0.10")
    )
    after_maturity = client.post(
        "/api/reference-prices", json=price_body(asset, "2027-01-05", pu="100000")
    )

    assert Decimal(on_maturity["pu"]) == Decimal("100000")
    assert Decimal(on_maturity["rate"]) == 0
    assert problem(typed_rate, 422) == [("VALIDATION_ERROR", "rate")]
    assert problem(after_maturity, 422) == [("CONTRACT_MATURED", "reference_date")]


def test_a_price_write_saves_only_the_fact(
    app: tuple[TestClient, str], contracts: dict[str, str]
) -> None:
    # OQ-31: setting, correcting and removing a price, also on processed dates, marks nothing,
    # keeps every date's status and processing time, and creates no job.
    client, database_url = app
    asset = contracts["DI1F28"]
    sql(
        database_url,
        "INSERT INTO processing.date_status (date, portfolio, portfolio_processed_at)"
        " SELECT d::date, 'PROCESSED', now()"
        " FROM generate_series(date '2027-01-05', date '2027-01-07', interval '1 day') AS d",
    )
    statuses = "SELECT * FROM processing.date_status ORDER BY date"
    before = (sql(database_url, statuses), derived_rows(database_url))

    _set(client, price_body(asset, DAY, rate="0.10"))
    corrected = _set(client, price_body(asset, DAY, rate="0.11"))
    removed = client.delete(f"/api/reference-prices/{corrected['id']}")

    assert removed.status_code == 204, removed.text
    assert _days(client, asset, DAY, DAY) == []
    assert client.get("/api/processing/requests").json()["items"] == []
    assert (sql(database_url, statuses), derived_rows(database_url)) == before
    # Only the three seeded statuses: no request, outbox message or result was ever written.
    assert {table: n for table, n in before[1].items() if n} == {"processing.date_status": 3}
