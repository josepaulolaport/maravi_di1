"""The module routes through the real app (``create_app``) against PostgreSQL 16: each router is
registered under ``/api`` and reaches its service with the composition's providers (interfaces.md
"DI composition", "HTTP endpoints"; the frontend's ``API_BASE``).

One smoke path per router, with no fakes: Asset over its repository; Ledger and Prices over Asset's
reader, the real Pricing and the app's clock (OQ-14); Portfolio's read models on the request's
fresh Unit of Work (OQ-23, OQ-35); Processing's queue (OQ-29). Each module that reads "today"
proves it is the app's `FixedClock` (18/10/2026): the system date, 19/10/2026, is refused.

The expected PU is spec §4.1's ``PU = 100000 / (1 + taxa)^(dias_corridos/365)`` for DI1F28
(maturity 03/01/2028) at 10% a.a. on 14/10/2026: 446 calendar days,
100000 / 1.10^(446/365) = 89006.4625467350 at 10 dp (OQ-3), the
same as the frontend fixture (``frontend/src/api/mocks/fixtures.ts``). The behaviour of each
route is the modules' own tests' business; these tests only prove the wiring.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from di1.main import create_app
from di1.platform.config import Settings
from tests.fakes.clock import FixedClock
from tests.integration.databases import fresh_database_url, psycopg_url

BACKEND = Path(__file__).resolve().parents[3]
TODAY = date(2026, 10, 18)
PROBLEM_JSON = "application/problem+json"


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _seed_catalogue_roots(database_url: str) -> None:
    """The instrument type and asset class, which have no HTTP route (seeded data)."""
    with psycopg.connect(psycopg_url(database_url), autocommit=True) as connection:
        connection.execute(
            "INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuros')"
        )
        connection.execute(
            "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
            " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros')"
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    for url in fresh_database_url():
        _migrate(url)
        _seed_catalogue_roots(url)
        app = create_app(Settings(database_url=SecretStr(url)), clock=FixedClock(TODAY))
        with TestClient(app) as test_client:
            yield test_client


def _create_di1f28(client: TestClient) -> str:
    product = client.post(
        "/api/products",
        json={
            "asset_class_id": 1,
            "code": "DI1",
            "name": "Futuro DI1",
            "futures": {
                "face_value": "100000",
                "contract_multiplier": "1",
                "settlement_method": "CASH",
                "settlement_description": "Liquidação financeira",
            },
        },
    )
    assert product.status_code == 201, product.text
    instrument = client.post(
        "/api/instruments",
        json={"product_id": product.json()["id"], "code": "DI1F28", "maturity_date": "2028-01-03"},
    )
    assert instrument.status_code == 201, instrument.text
    instrument_id: str = instrument.json()["id"]
    return instrument_id


def _trade(asset_id: str, entry_date: str) -> dict[str, Any]:
    return {
        "type": "TRADE",
        "asset_id": asset_id,
        "date": entry_date,
        "time": "14:10",
        "signed_quantity": 10,
        "input_kind": "RATE",
        "execution_rate": "0.10",
    }


def test_asset_routes_are_served_under_api(client: TestClient) -> None:
    asset_id = _create_di1f28(client)

    types = client.get("/api/instrument-types")
    instruments = client.get("/api/instruments", params={"search": "f28"})

    assert types.status_code == 200
    assert [t["code"] for t in types.json()["items"]] == ["FUTURE"]
    assert [i["id"] for i in instruments.json()["items"]] == [asset_id]


def test_ledger_records_a_trade_priced_by_pricing_over_asset(client: TestClient) -> None:
    asset_id = _create_di1f28(client)

    created = client.post("/api/ledger/entries", json=_trade(asset_id, "2026-10-14"))

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["asset_code"], body["instrument_type_code"]) == ("DI1F28", "FUTURE")
    assert (body["execution_pu"], body["execution_rate"]) == ("89006.4625467350", "0.10")


def test_ledger_lists_and_deletes_entries(client: TestClient) -> None:
    cash = {"type": "CASH", "date": "2026-10-14", "time": "09:00", "cash_amount": "1500000.00"}
    cash_id = client.post("/api/ledger/entries", json=cash).json()["id"]
    page = {"start_date": "2026-10-01", "end_date": "2026-10-18"}

    listed = client.get("/api/ledger/entries", params=page)
    deleted = client.post("/api/ledger/entries/deletions", json={"ids": [cash_id]})
    after = client.get("/api/ledger/entries", params=page)

    assert [e["id"] for e in listed.json()["items"]] == [cash_id]
    assert deleted.status_code == 204
    assert after.json() == {"items": [], "next_cursor": None}


def test_ledger_reads_today_from_the_app_clock(client: TestClient) -> None:
    asset_id = _create_di1f28(client)

    response = client.post("/api/ledger/entries", json=_trade(asset_id, "2026-10-19"))

    assert (response.status_code, response.headers["content-type"]) == (422, PROBLEM_JSON)
    assert [e["code"] for e in response.json()["errors"]] == ["FUTURE_DATE"]


def test_module_routes_are_not_served_at_the_root(client: TestClient) -> None:
    assert client.get("/instrument-types").status_code == 404
    assert client.get("/health").status_code == 200


def test_prices_sets_a_reference_price_priced_by_pricing(client: TestClient) -> None:
    asset_id = _create_di1f28(client)
    body = {
        "asset_id": asset_id,
        "reference_date": "2026-10-14",
        "input_kind": "RATE",
        "rate": "0.10",
    }

    created = client.post("/api/reference-prices", json=body)
    listed = client.get(
        "/api/reference-prices",
        params={"asset_id": asset_id, "start_date": "2026-10-14", "end_date": "2026-10-14"},
    )

    assert created.status_code == 201, created.text
    assert (created.json()["source"], created.json()["pu"]) == ("MANUAL", "89006.4625467350")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 1


def test_asset_shows_each_contracts_latest_reference_price(client: TestClient) -> None:
    """OQ-48: ``last_reference`` is the latest preferred price, read from Prices on the request's
    session. DI1F28 at 10% a.a. on 15/10/2026: 445 calendar days to 03/01/2028, so spec §4.1 gives
    100000 / 1.10^(445/365) = 89029.7072854500 at 10 dp (OQ-3)."""
    asset_id = _create_di1f28(client)
    assert client.get(f"/api/instruments/{asset_id}").json()["last_reference"] is None
    for day in ("2026-10-14", "2026-10-15"):
        body = {"asset_id": asset_id, "reference_date": day, "input_kind": "RATE", "rate": "0.10"}
        assert client.post("/api/reference-prices", json=body).status_code == 201

    listed = client.get("/api/instruments", params={"search": "f28"}).json()["items"]
    one = client.get(f"/api/instruments/{asset_id}").json()

    expected = {
        "reference_date": "2026-10-15",
        "pu": "89029.7072854500",
        "rate": "0.10",
        "source": "MANUAL",
    }
    assert [item["last_reference"] for item in listed] == [expected]
    assert one["last_reference"] == expected


def test_prices_reads_today_from_the_app_clock(client: TestClient) -> None:
    asset_id = _create_di1f28(client)
    body = {"asset_id": asset_id, "reference_date": "2026-10-19", "input_kind": "RATE"}

    response = client.post("/api/reference-prices", json={**body, "rate": "0.10"})

    assert response.status_code == 422
    assert [e["code"] for e in response.json()["errors"]] == ["FUTURE_DATE"]


def test_portfolio_summary_of_an_unprocessed_date(client: TestClient) -> None:
    response = client.get("/api/portfolio/summary", params={"date": "2026-10-14"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["cash"]["status"], body["positions"]["status"]) == (
        "NOT_PROCESSED",
        "NOT_PROCESSED",
    )
    assert body["aum"] is None


def test_portfolio_reads_today_from_the_app_clock(client: TestClient) -> None:
    response = client.get("/api/portfolio/summary", params={"date": "2026-10-19"})

    assert response.status_code == 422
    assert [e["code"] for e in response.json()["errors"]] == ["FUTURE_DATE"]


def test_processing_queues_and_lists_a_request(client: TestClient) -> None:
    body = {"start_date": "2026-10-14", "end_date": "2026-10-18", "scope": "ALL"}

    created = client.post("/api/processing/requests", json=body)
    listed = client.get("/api/processing/requests")

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "QUEUED"
    assert [r["id"] for r in listed.json()["items"]] == [created.json()["id"]]


def test_processing_reads_today_from_the_app_clock(client: TestClient) -> None:
    body = {"start_date": "2026-10-14", "end_date": "2026-10-19", "scope": "ALL"}

    response = client.post("/api/processing/requests", json=body)

    assert response.status_code == 422
    errors = [(e["code"], e["field"]) for e in response.json()["errors"]]
    assert errors == [("FUTURE_DATE", "end_date")]


def test_processing_refuses_a_range_longer_than_3660_dates(client: TestClient) -> None:
    # 2016-10-10 .. 2026-10-18 is 3,661 dates, ends included.
    body = {"start_date": "2016-10-10", "end_date": "2026-10-18", "scope": "ALL"}

    response = client.post("/api/processing/requests", json=body)

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "code": "INVALID_RANGE",
            "message": "O período deve ter no máximo 3.660 dias.",
            "field": "end_date",
        }
    ]
