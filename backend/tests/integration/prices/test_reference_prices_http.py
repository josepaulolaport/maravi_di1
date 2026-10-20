"""``/reference-prices`` over HTTP against PostgreSQL, compared with the frozen frontend contract
(``frontend/src/api/contract/prices.ts`` and the MSW fixtures and handler at 57b4df0; OQ-26
item 8): shapes, decimals as strings, status codes and problem+json errors."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr

from di1.composition.dependencies import get_unit_of_work as composition_unit_of_work
from di1.main import create_app
from di1.modules.prices.application.services.price_service import PriceService
from di1.modules.prices.dependencies import build_price_service
from di1.modules.prices.presentation.http.router import create_router
from di1.platform.config import Settings
from di1.platform.database.unit_of_work import UnitOfWork
from tests.fakes.clock import FixedClock
from tests.integration.prices.conftest import DI1F28, DI1F29, INSTRUMENTS, MATURED, PRODUCT, TODAY
from tests.support.db import psycopg_url
from tests.unit.prices.fakes import CALCULATED_PU, CALCULATED_RATE, FakeAssets, FakePricing

# frontend/src/api/mocks/fixtures.ts `referencePrices`, DI1F28 and DI1F29.
FIXTURES = [
    (1, DI1F28, "2026-09-24", "B3", "88215.0712246655", "0.1032", "2026-09-24T18:00:00-03:00"),
    (2, DI1F28, "2026-09-30", "MANUAL", "88509.2489449811", "0.1017", "2026-09-30T18:00:00-03:00"),
    (3, DI1F28, "2026-10-05", "MANUAL", "88777.4109547747", "0.1002", "2026-10-05T18:00:00-03:00"),
    (4, DI1F28, "2026-10-08", "B3", "88817.1246020680", "0.1005", "2026-10-08T18:00:00-03:00"),
    (5, DI1F28, "2026-10-09", "MANUAL", "88910.3037976557", "0.0998", "2026-10-09T18:00:00-03:00"),
    (6, DI1F28, "2026-10-14", "MANUAL", "89006.4625467350", "0.10", "2026-10-14T18:00:00-03:00"),
    (7, DI1F28, "2026-10-15", "B3", "89128.4824345118", "0.0990", "2026-10-15T18:00:00-03:00"),
    (8, DI1F28, "2026-10-16", "MANUAL", "89250.3147019396", "0.0980", "2026-10-17T10:00:00-03:00"),
    (10, DI1F28, "2026-10-16", "B3", "89240.4279488087", "0.0981", "2026-10-16T19:00:00-03:00"),
    (11, DI1F29, "2026-10-15", "MANUAL", "80206.1333187932", "0.1045", "2026-10-15T18:00:00-03:00"),
]
REFERENCE_PRICE_KEYS = {
    "id",
    "asset_id",
    "reference_date",
    "source",
    "input_kind",
    "pu",
    "rate",
    "created_at",
}


def _fixture_id(n: int) -> str:
    return f"7e000000-0000-4000-8000-{n:012d}"


def _fixture(n: int) -> dict[str, Any]:
    _, asset, day, source, pu, rate, created = next(f for f in FIXTURES if f[0] == n)
    return {
        "id": _fixture_id(n),
        "asset_id": str(asset),
        "reference_date": day,
        "source": source,
        "input_kind": "RATE",
        "pu": pu,
        "rate": rate,
        "created_at": created,
    }


class Api:
    def __init__(self, client: TestClient, url: str) -> None:
        self.client = client
        self.url = url

    def rows(self) -> list[tuple[Any, ...]]:
        with psycopg.connect(psycopg_url(self.url)) as connection:
            return list(
                connection.execute(
                    "SELECT id, asset_id, reference_date, source, input_kind, pu::text, rate::text"
                    " FROM prices.reference_prices ORDER BY reference_date, source"
                )
            )


@pytest.fixture
def api(migrated_database_url: str, assets: FakeAssets) -> Iterator[Api]:
    _seed(migrated_database_url)
    app = create_app(Settings(database_url=SecretStr(migrated_database_url)))

    uow_dependency = Depends(composition_unit_of_work)

    def service(uow: UnitOfWork = uow_dependency) -> PriceService:
        return build_price_service(
            uow, assets=assets, pricing=FakePricing(), clock=FixedClock(TODAY)
        )

    app.include_router(create_router(get_service=service))
    with TestClient(app) as client:
        yield Api(client, migrated_database_url)


def _seed(url: str) -> None:
    with psycopg.connect(psycopg_url(url)) as connection:
        connection.execute(
            "INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuros')"
        )
        connection.execute(
            "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
            " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de juros')"
        )
        connection.execute(
            "INSERT INTO asset.products (id, asset_class_id, code, name)"
            " VALUES (%s, 1, 'DI1', 'DI1')",
            (PRODUCT,),
        )
        for instrument_id, (code, maturity) in INSTRUMENTS.items():
            connection.execute(
                "INSERT INTO asset.instruments (id, product_id, code, maturity_date)"
                " VALUES (%s, %s, %s, %s)",
                (instrument_id, PRODUCT, code, maturity),
            )
        for n, asset, day, source, pu, rate, created in FIXTURES:
            connection.execute(
                "INSERT INTO prices.reference_prices (id, asset_id, reference_date, source,"
                " input_kind, pu, rate, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, 'RATE', %s, %s, %s, %s)",
                (_fixture_id(n), asset, day, source, pu, rate, created, created),
            )


def _same(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Equal field by field; ``created_at`` as an instant, since the offset may differ."""
    assert set(actual) == REFERENCE_PRICE_KEYS
    assert {k: v for k, v in actual.items() if k != "created_at"} == {
        k: v for k, v in expected.items() if k != "created_at"
    }
    assert datetime.fromisoformat(actual["created_at"]) == datetime.fromisoformat(
        expected["created_at"]
    )


class TestList:
    def test_one_day_per_date_with_a_price_newest_first_manual_preferred(self, api: Api) -> None:
        response = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-09-01", "end_date": "2026-10-19"},
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert set(response.json()) == {"items"}
        expected_days = [
            ("2026-10-16", 8, [8, 10]),
            ("2026-10-15", 7, [7]),
            ("2026-10-14", 6, [6]),
            ("2026-10-09", 5, [5]),
            ("2026-10-08", 4, [4]),
            ("2026-10-05", 3, [3]),
            ("2026-09-30", 2, [2]),
            ("2026-09-24", 1, [1]),
        ]
        assert [set(item) for item in items] == [{"reference_date", "preferred", "sources"}] * 8
        assert [item["reference_date"] for item in items] == [d for d, _, _ in expected_days]
        for item, (_, preferred, sources) in zip(items, expected_days, strict=True):
            _same(item["preferred"], _fixture(preferred))
            assert len(item["sources"]) == len(sources)
            for actual, n in zip(item["sources"], sources, strict=True):
                _same(actual, _fixture(n))

    def test_decimals_keep_their_typed_scale_as_strings(self, api: Api) -> None:
        response = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-10-14", "end_date": "2026-10-14"},
        )

        price = response.json()["items"][0]["preferred"]
        assert (price["pu"], price["rate"]) == ("89006.4625467350", "0.10")

    def test_a_range_without_prices_is_empty_no_carry_forward(self, api: Api) -> None:
        response = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-10-17", "end_date": "2026-10-19"},
        )

        assert (response.status_code, response.json()) == (200, {"items": []})

    def test_a_range_ending_after_today_is_accepted_and_future_days_are_empty(
        self, api: Api
    ) -> None:
        # GAP-D-1 (user, 2026-10-19): reads accept dates after today (19/10) and return no
        # day for them; only writes are refused after today.
        response = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-10-15", "end_date": "2026-11-30"},
        )

        assert response.status_code == 200
        assert [item["reference_date"] for item in response.json()["items"]] == [
            "2026-10-16",
            "2026-10-15",
        ]

    def test_a_range_entirely_after_today_is_empty(self, api: Api) -> None:
        response = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-10-20", "end_date": "2026-12-31"},
        )

        assert (response.status_code, response.json()) == (200, {"items": []})

    def test_an_unknown_asset_and_an_inverted_range_are_422(self, api: Api) -> None:
        response = api.client.get(
            "/reference-prices",
            params={
                "asset_id": "6f1c2a10-0000-4000-8000-00000000dead",
                "start_date": "2026-10-16",
                "end_date": "2026-10-15",
            },
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["errors"] == [
            {
                "code": "INVALID_RANGE",
                "message": "A data inicial deve ser anterior ou igual à data final.",
                "field": "start_date",
            },
            {"code": "VALIDATION_ERROR", "message": "Selecione um contrato.", "field": "asset_id"},
        ]

    def test_missing_query_parameters_are_422(self, api: Api) -> None:
        response = api.client.get("/reference-prices", params={"asset_id": str(DI1F28)})

        assert response.status_code == 422
        assert {e["field"] for e in response.json()["errors"]} == {"start_date", "end_date"}


class TestSet:
    def test_a_typed_pu_answers_201_with_a_manual_price(self, api: Api) -> None:
        response = api.client.post(
            "/reference-prices",
            json={
                "asset_id": str(DI1F28),
                "reference_date": "2026-10-19",
                "input_kind": "PU",
                "pu": "89300.1234567890",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert set(body) == REFERENCE_PRICE_KEYS
        assert {k: body[k] for k in ("asset_id", "reference_date", "source", "input_kind")} == {
            "asset_id": str(DI1F28),
            "reference_date": "2026-10-19",
            "source": "MANUAL",
            "input_kind": "PU",
        }
        assert (body["pu"], body["rate"]) == ("89300.1234567890", str(CALCULATED_RATE))

    def test_a_typed_rate_answers_with_the_calculated_pu(self, api: Api) -> None:
        response = api.client.post(
            "/reference-prices",
            json={
                "asset_id": str(DI1F29),
                "reference_date": "2026-10-16",
                "input_kind": "RATE",
                "rate": "0.1040",
            },
        )

        assert response.status_code == 201
        assert (response.json()["pu"], response.json()["rate"]) == (str(CALCULATED_PU), "0.1040")

    def test_corrigir_replaces_the_manual_price_with_a_new_id_and_keeps_b3(self, api: Api) -> None:
        response = api.client.post(
            "/reference-prices",
            json={
                "asset_id": str(DI1F28),
                "reference_date": "2026-10-16",
                "input_kind": "PU",
                "pu": "89255",
            },
        )

        assert response.status_code == 201
        new_id = response.json()["id"]
        assert new_id != _fixture_id(8)
        on_the_day = [row for row in api.rows() if row[2] == date(2026, 10, 16)]
        assert [(str(r[0]), r[3], r[5]) for r in on_the_day] == [
            (_fixture_id(10), "B3", "89240.4279488087"),
            (new_id, "MANUAL", "89255"),
        ]

    @pytest.mark.parametrize(
        ("body", "status", "errors"),
        [
            (
                {"reference_date": "2026-10-20", "input_kind": "PU", "pu": "89000"},
                422,
                [
                    {
                        "code": "FUTURE_DATE",
                        "message": "A data não pode ser posterior a hoje.",
                        "field": "reference_date",
                    }
                ],
            ),
            (
                {"asset_id": str(MATURED), "input_kind": "PU", "pu": "100000"},
                422,
                [
                    {
                        "code": "CONTRACT_MATURED",
                        "message": "O contrato já venceu nesta data.",
                        "field": "reference_date",
                    }
                ],
            ),
            (
                {"input_kind": "PU", "pu": "89000.12345678901"},
                422,
                [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Use no máximo 10 casas decimais.",
                        "field": "pu",
                    }
                ],
            ),
            (
                {"input_kind": "RATE", "rate": "0.1234567890123"},
                422,
                [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Use no máximo 12 casas decimais.",
                        "field": "rate",
                    }
                ],
            ),
            (
                {"input_kind": "PU", "pu": "0"},
                422,
                [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "O PU deve ser maior que zero.",
                        "field": "pu",
                    }
                ],
            ),
            (
                {"input_kind": "RATE"},
                422,
                [{"code": "VALIDATION_ERROR", "message": "Informe a taxa.", "field": "rate"}],
            ),
            (
                {"asset_id": "6f1c2a10-0000-4000-8000-00000000dead", "input_kind": "PU", "pu": "1"},
                422,
                [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Selecione um contrato.",
                        "field": "asset_id",
                    }
                ],
            ),
            (
                {
                    "asset_id": "6f1c2a10-0000-4000-8000-00000000dead",
                    "reference_date": "2026-10-20",
                    "input_kind": "PU",
                    "pu": "0",
                },
                422,
                [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "Selecione um contrato.",
                        "field": "asset_id",
                    },
                    {
                        "code": "FUTURE_DATE",
                        "message": "A data não pode ser posterior a hoje.",
                        "field": "reference_date",
                    },
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "O PU deve ser maior que zero.",
                        "field": "pu",
                    },
                ],
            ),
            (
                # Digits other than ASCII 0-9 are not a typed number (Arabic-Indic 89250).
                {"input_kind": "PU", "pu": "\u0668\u0669\u0662\u0665\u0660"},
                422,
                [{"code": "VALIDATION_ERROR", "message": "Valor inválido.", "field": "pu"}],
            ),
            (
                {"input_kind": "PU", "pu": 89000.5},
                422,
                [{"code": "VALIDATION_ERROR", "message": "Valor inválido.", "field": "pu"}],
            ),
        ],
    )
    def test_refusals_are_problem_json_and_write_nothing(
        self, api: Api, body: dict[str, Any], status: int, errors: list[dict[str, Any]]
    ) -> None:
        before = api.rows()
        payload = {"asset_id": str(DI1F28), "reference_date": "2026-10-16", **body}

        response = api.client.post("/reference-prices", json=payload)

        assert response.status_code == status
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["errors"] == errors
        assert api.rows() == before


class TestDelete:
    def test_delete_answers_204_and_b3_becomes_preferred(self, api: Api) -> None:
        response = api.client.delete(f"/reference-prices/{_fixture_id(8)}")

        assert (response.status_code, response.content) == (204, b"")
        day = api.client.get(
            "/reference-prices",
            params={"asset_id": str(DI1F28), "start_date": "2026-10-16", "end_date": "2026-10-16"},
        ).json()["items"][0]
        _same(day["preferred"], _fixture(10))
        assert [s["id"] for s in day["sources"]] == [_fixture_id(10)]

    def test_an_unknown_price_is_404_problem_json(self, api: Api) -> None:
        response = api.client.delete(f"/reference-prices/{UUID(int=1)}")

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["errors"] == [
            {"code": "NOT_FOUND", "message": "Preço de referência não encontrado.", "field": None}
        ]
