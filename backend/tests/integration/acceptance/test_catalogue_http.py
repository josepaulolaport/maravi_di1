"""The instrument catalogue over HTTP (challenge §3, requirement 1; spec §3; OQ-33).

A user registers the DI1 product and its contracts, then finds them by search. Codes are trimmed
and upper-cased; search is a case- and accent-insensitive substring; an unknown id in the body
is a 422 on its field; ``last_reference`` is null for now.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.acceptance.support import (
    acceptance_app,
    create_di1_product,
    create_instrument,
    problem,
)

TODAY = date(2027, 1, 1)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with acceptance_app(TODAY) as (client, _):
        yield client


def test_register_and_find_the_challenge_contract(client: TestClient) -> None:
    product_id = create_di1_product(client)
    instrument_id = create_instrument(client, product_id, "  di1f28 ", "2028-01-01")

    found = client.get("/api/instruments", params={"search": "F28"}).json()["items"]

    assert [(i["id"], i["code"], i["maturity_date"]) for i in found] == [
        (instrument_id, "DI1F28", "2028-01-01")
    ]
    assert found[0]["product_code"] == "DI1"
    assert found[0]["last_reference"] is None


def test_product_search_ignores_case_and_accents(client: TestClient) -> None:
    product_id = create_di1_product(client)  # "Futuro de Depósito Interfinanceiro"

    found = client.get("/api/products", params={"search": "DEPOSITO"}).json()["items"]

    assert [p["id"] for p in found] == [product_id]
    assert Decimal(found[0]["futures"]["face_value"]) == Decimal("100000")


def test_an_unknown_product_is_a_field_error(client: TestClient) -> None:
    response = client.post(
        "/api/instruments",
        json={
            "product_id": "00000000-0000-0000-0000-000000000000",
            "code": "DI1F28",
            "maturity_date": "2028-01-01",
        },
    )

    assert problem(response, 422) == [("VALIDATION_ERROR", "product_id")]


def test_an_unknown_asset_class_is_a_field_error(client: TestClient) -> None:
    response = client.post(
        "/api/products", json={"asset_class_id": 999, "code": "DI1", "name": "Futuro DI1"}
    )

    assert problem(response, 422) == [("VALIDATION_ERROR", "asset_class_id")]
