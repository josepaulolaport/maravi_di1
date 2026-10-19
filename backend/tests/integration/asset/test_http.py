"""Asset HTTP routes against PostgreSQL 16, through the real app (interfaces.md "HTTP endpoints";
OQ-26 item 8: the shapes of ``frontend/src/api/contract/asset.ts``).

The MSW fixtures (``frontend/src/api/mocks/fixtures.ts``) are the golden examples of the shapes:
field names, decimals as strings, ``null`` rather than 0. Server-generated values (product and
instrument ids, ``created_at``) are compared by type only. ``last_reference`` is each instrument's
latest preferred reference price from `prices.public.LatestPriceReader` (OQ-48), ``null`` when it
has none; a fake reader stands in for Prices.
Errors are problem+json (OQ-15) with pt-BR messages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from di1.composition.dependencies import get_unit_of_work
from di1.main import create_app
from di1.modules.asset.presentation.http.router import create_router
from di1.modules.prices.public import PriceSource
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from tests.integration.asset.conftest import Di1Catalogue, seed_di1
from tests.integration.asset.latest_prices import FakeLatestPrices, price

# fixtures.ts: instrumentTypes, products[0] and instruments (DI1F27…DI1F30).
GOLDEN_INSTRUMENT_TYPES = {
    "items": [
        {
            "id": 1,
            "code": "FUTURE",
            "name": "Futuros",
            "asset_classes": [
                {"id": 1, "code": "INTEREST_RATE_FUTURE", "name": "Futuros de Taxa de Juros"}
            ],
        }
    ]
}
GOLDEN_PRODUCT = {
    "id": "6f1c2a10-0000-4000-8000-000000000001",
    "code": "DI1",
    "name": "Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia",
    "asset_class": {"id": 1, "code": "INTEREST_RATE_FUTURE", "name": "Futuros de Taxa de Juros"},
    "instrument_type": {"id": 1, "code": "FUTURE", "name": "Futuros"},
    "instrument_count": 4,
    "futures": {
        "face_value": "100000",
        "contract_multiplier": "1",
        "settlement_method": "CASH",
        "settlement_description": "Liquidação financeira",
    },
    "created_at": "2026-10-01T09:00:00-03:00",
}
GOLDEN_INSTRUMENTS = [
    {
        "id": f"6f1c2a10-0000-4000-8000-0000000000{suffix}",
        "code": code,
        "product_id": "6f1c2a10-0000-4000-8000-000000000001",
        "product_code": "DI1",
        "maturity_date": maturity,
        "last_reference": None,
        "created_at": "2026-10-01T09:00:00-03:00",
    }
    for code, suffix, maturity in [
        ("DI1F27", "f7", "2027-01-04"),
        ("DI1F28", "f8", "2028-01-03"),
        ("DI1F29", "f9", "2029-01-02"),
        ("DI1F30", "fa", "2030-01-02"),
    ]
]
GENERATED = ("id", "product_id", "created_at")


def _with_generated(golden: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """The golden example with the server-generated values taken from ``actual``, after checking
    they have the contract's types (a UUID, an instant with its offset)."""
    for key in GENERATED:
        if key in golden:
            if key == "created_at":
                assert datetime.fromisoformat(actual[key]).tzinfo is not None
            else:
                UUID(actual[key])
    return golden | {key: actual[key] for key in GENERATED if key in golden}


def _seed(settings: Settings) -> Di1Catalogue:
    async def run() -> Di1Catalogue:
        engine = create_engine(settings)
        try:
            return await seed_di1(create_session_factory(engine))
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def seeded(settings: Settings) -> Di1Catalogue:
    return _seed(settings)


@pytest.fixture
def latest_prices() -> FakeLatestPrices:
    """No instrument has a price unless a test gives it one."""
    return FakeLatestPrices()


@pytest.fixture
def client(
    settings: Settings, seeded: Di1Catalogue, latest_prices: FakeLatestPrices
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.include_router(create_router(get_unit_of_work, lambda uow: latest_prices))
    with TestClient(app) as client:
        yield client


def _problem(response: Any) -> tuple[int, str, list[tuple[str, str, str | None]]]:
    body = response.json()
    assert body["type"] == "about:blank"
    errors = [(e["code"], e["message"], e["field"]) for e in body["errors"]]
    return response.status_code, response.headers["content-type"], errors


PROBLEM = "application/problem+json"


class TestShapes:
    def test_instrument_types_with_their_classes(self, client: TestClient) -> None:
        response = client.get("/instrument-types")

        assert (response.status_code, response.json()) == (200, GOLDEN_INSTRUMENT_TYPES)

    def test_products(self, client: TestClient, seeded: Di1Catalogue) -> None:
        body = client.get("/products").json()

        assert list(body) == ["items"]
        (product,) = body["items"]
        assert product == _with_generated(GOLDEN_PRODUCT, product)
        assert product["id"] == str(seeded.di1_id)

    def test_one_product(self, client: TestClient, seeded: Di1Catalogue) -> None:
        response = client.get(f"/products/{seeded.di1_id}")

        assert response.status_code == 200
        assert response.json() == _with_generated(GOLDEN_PRODUCT, response.json())

    def test_instruments_by_maturity(self, client: TestClient, seeded: Di1Catalogue) -> None:
        body = client.get("/instruments", params={"product_id": str(seeded.di1_id)}).json()

        assert list(body) == ["items"]
        assert body["items"] == [
            _with_generated(golden, actual)
            for golden, actual in zip(GOLDEN_INSTRUMENTS, body["items"], strict=True)
        ]
        assert [i["product_id"] for i in body["items"]] == [str(seeded.di1_id)] * 4

    def test_one_instrument(self, client: TestClient, seeded: Di1Catalogue) -> None:
        response = client.get(f"/instruments/{seeded.instrument_ids['DI1F28']}")

        assert response.status_code == 200
        assert response.json() == _with_generated(GOLDEN_INSTRUMENTS[1], response.json())

    def test_creating_an_instrument_answers_201_with_it(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = {"product_id": str(seeded.di1_id), "code": " di1n27 ", "maturity_date": "2027-07-01"}

        response = client.post("/instruments", json=body)

        assert response.status_code == 201
        created = response.json()
        assert created == _with_generated(
            {
                "id": "",
                "code": "DI1N27",
                "product_id": "",
                "product_code": "DI1",
                "maturity_date": "2027-07-01",
                "last_reference": None,
                "created_at": "",
            },
            created,
        )
        assert client.get(f"/instruments/{created['id']}").json() == created
        assert client.get(f"/products/{seeded.di1_id}").json()["instrument_count"] == 5


class TestFilters:
    def test_products_by_type_code_and_search(self, client: TestClient) -> None:
        def codes(**params: str) -> list[str]:
            return [p["code"] for p in client.get("/products", params=params).json()["items"]]

        assert codes(instrument_type="FUTURE") == ["DI1"]
        assert codes(instrument_type="") == ["DI1"]
        assert codes(instrument_type="\x00") == []
        assert codes(instrument_type="OPTION") == []
        assert codes(search="depósitos") == ["DI1"]
        assert codes(search="depositos") == ["DI1"]
        assert codes(search="dólar") == []

    def test_instruments_by_search(self, client: TestClient) -> None:
        items = client.get("/instruments", params={"search": "f29"}).json()["items"]

        assert [i["code"] for i in items] == ["DI1F29"]


class TestErrors:
    def test_an_unknown_product_or_instrument_is_404(self, client: TestClient) -> None:
        for path, message in [
            (f"/products/{uuid4()}", "Produto não encontrado."),
            (f"/instruments/{uuid4()}", "Contrato não encontrado."),
        ]:
            assert _problem(client.get(path)) == (404, PROBLEM, [("NOT_FOUND", message, None)])

    def test_a_duplicate_code_is_422_on_code(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = {"product_id": str(seeded.di1_id), "code": "di1f27", "maturity_date": "2027-01-04"}

        assert _problem(client.post("/instruments", json=body)) == (
            422,
            PROBLEM,
            [("VALIDATION_ERROR", "Já existe um contrato com este código.", "code")],
        )

    def test_an_unknown_product_is_422_on_product_id(self, client: TestClient) -> None:
        body = {"product_id": str(uuid4()), "code": "DI1N27", "maturity_date": "2027-07-01"}

        assert _problem(client.post("/instruments", json=body)) == (
            422,
            PROBLEM,
            [("VALIDATION_ERROR", "Produto não encontrado.", "product_id")],
        )

    def test_a_future_without_maturity_is_422_on_maturity_date(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        # The field is required (contract CreateInstrumentRequest); null is allowed only for a
        # product that is not a future (spec §3).
        absent = {"product_id": str(seeded.di1_id), "code": "DI1N27"}
        null = absent | {"maturity_date": None}

        assert _problem(client.post("/instruments", json=absent)) == (
            422,
            PROBLEM,
            [("VALIDATION_ERROR", "Campo obrigatório.", "maturity_date")],
        )
        assert _problem(client.post("/instruments", json=null)) == (
            422,
            PROBLEM,
            [("VALIDATION_ERROR", "Informe o vencimento.", "maturity_date")],
        )

    def test_a_nul_in_the_code_is_422_on_code(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = {
            "product_id": str(seeded.di1_id),
            "code": "DI1\u0000N27",
            "maturity_date": "2027-07-01",
        }

        status, _, errors = _problem(client.post("/instruments", json=body))

        assert (status, [e[2] for e in errors]) == (422, ["code"])

    def test_malformed_input_is_422_on_its_field(self, client: TestClient) -> None:
        status, content_type, errors = _problem(
            client.post("/instruments", json={"product_id": "x", "maturity_date": "2027-13-01"})
        )

        assert (status, content_type) == (422, PROBLEM)
        assert sorted(errors, key=lambda e: e[2] or "") == [
            ("VALIDATION_ERROR", "Campo obrigatório.", "code"),
            ("VALIDATION_ERROR", "Valor inválido.", "maturity_date"),
            ("VALIDATION_ERROR", "Valor inválido.", "product_id"),
        ]

    def test_a_malformed_path_id_is_422(self, client: TestClient) -> None:
        assert _problem(client.get("/instruments/not-a-uuid"))[0] == 422


DAP = {
    "code": "DAP",
    "name": "Cupom de IPCA",
    "futures": {
        "face_value": "100000",
        "contract_multiplier": "1",
        "settlement_method": "CASH",
        "settlement_description": None,
    },
}


class TestCreateProduct:
    """``POST /products`` (interfaces.md "HTTP endpoints"); not used by the current UI."""

    def test_answers_201_with_the_product(self, client: TestClient, seeded: Di1Catalogue) -> None:
        body = DAP | {"asset_class_id": seeded.interest_rate_class_id}

        response = client.post("/products", json=body)

        assert response.status_code == 201
        created = response.json()
        assert created == _with_generated(
            {
                "id": "",
                "code": "DAP",
                "name": "Cupom de IPCA",
                "asset_class": GOLDEN_PRODUCT["asset_class"],
                "instrument_type": GOLDEN_PRODUCT["instrument_type"],
                "instrument_count": 0,
                "futures": DAP["futures"],
                "created_at": "",
            },
            created,
        )
        assert client.get(f"/products/{created['id']}").json() == created

    def test_the_code_is_stored_trimmed_and_upper_cased(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "code": " dap "}

        assert client.post("/products", json=body).json()["code"] == "DAP"

    def test_the_multiplier_defaults_to_one(self, client: TestClient, seeded: Di1Catalogue) -> None:
        futures = {"face_value": "100000", "settlement_method": "CASH"}
        body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "futures": futures}

        created = client.post("/products", json=body).json()

        assert created["futures"] == {
            "face_value": "100000",
            "contract_multiplier": "1",
            "settlement_method": "CASH",
            "settlement_description": None,
        }

    def test_a_future_without_its_specification_is_422_on_futures(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = {"asset_class_id": seeded.interest_rate_class_id, "code": "DAP", "name": "Cupom"}

        assert _problem(client.post("/products", json=body))[2] == [
            ("VALIDATION_ERROR", "Informe a especificação do contrato futuro.", "futures")
        ]

    @pytest.mark.parametrize("asset_class_id", [999, 40000])
    def test_an_unknown_class_is_422_on_asset_class_id(
        self, client: TestClient, asset_class_id: int
    ) -> None:
        body = DAP | {"asset_class_id": asset_class_id}

        assert _problem(client.post("/products", json=body)) == (
            422,
            PROBLEM,
            [("VALIDATION_ERROR", "Classe de ativo não encontrada.", "asset_class_id")],
        )

    @pytest.mark.parametrize("face_value", [100000, 1.5, "1e5", "Infinity", "NaN", "", "1,5"])
    def test_decimals_are_plain_decimal_strings(
        self, client: TestClient, seeded: Di1Catalogue, face_value: object
    ) -> None:
        futures = dict(DAP["futures"]) | {"face_value": face_value}  # type: ignore[arg-type]
        body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "futures": futures}

        status, _, errors = _problem(client.post("/products", json=body))

        assert (status, [e[2] for e in errors]) == (422, ["futures.face_value"])

    def test_a_duplicate_code_is_422_on_code(
        self, client: TestClient, seeded: Di1Catalogue
    ) -> None:
        body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "code": "di1"}

        assert _problem(client.post("/products", json=body))[2] == [
            ("VALIDATION_ERROR", "Já existe um produto com este código.", "code")
        ]


class TestLastReference:
    """``Instrument.last_reference`` (OQ-48, reversing OQ-33 item 4): the latest preferred price,
    with its own date (OQ-19 item 5); ``null`` for an instrument without one."""

    def test_each_listed_instrument_carries_its_latest_price(
        self, client: TestClient, seeded: Di1Catalogue, latest_prices: FakeLatestPrices
    ) -> None:
        f28, f29 = seeded.instrument_ids["DI1F28"], seeded.instrument_ids["DI1F29"]
        latest_prices.latest[f28] = price(f28, date(2026, 10, 16), "89102.2226533433", "0.0995")
        latest_prices.latest[f29] = price(
            f29, date(2026, 10, 15), "82057.00", None, source=PriceSource.B3
        )

        items = client.get("/instruments").json()["items"]

        assert {i["code"]: i["last_reference"] for i in items} == {
            "DI1F27": None,
            "DI1F28": {
                "reference_date": "2026-10-16",
                "pu": "89102.2226533433",
                "rate": "0.0995",
                "source": "MANUAL",
            },
            "DI1F29": {
                "reference_date": "2026-10-15",
                "pu": "82057.00",
                "rate": None,
                "source": "B3",
            },
            "DI1F30": None,
        }

    def test_a_listing_reads_the_prices_once_for_its_instruments(
        self, client: TestClient, seeded: Di1Catalogue, latest_prices: FakeLatestPrices
    ) -> None:
        client.get("/instruments", params={"search": "f2"})

        assert latest_prices.calls == [
            frozenset(seeded.instrument_ids[c] for c in ("DI1F27", "DI1F28", "DI1F29"))
        ]

    def test_an_empty_listing_reads_no_prices(
        self, client: TestClient, latest_prices: FakeLatestPrices
    ) -> None:
        assert client.get("/instruments", params={"search": "x"}).json() == {"items": []}
        assert latest_prices.calls == []

    def test_one_instrument_carries_its_latest_price(
        self, client: TestClient, seeded: Di1Catalogue, latest_prices: FakeLatestPrices
    ) -> None:
        f28 = seeded.instrument_ids["DI1F28"]
        latest_prices.latest[f28] = price(f28, date(2026, 10, 16), "89102.2226533433", "0.0995")

        body = client.get(f"/instruments/{f28}").json()

        assert body["last_reference"] == {
            "reference_date": "2026-10-16",
            "pu": "89102.2226533433",
            "rate": "0.0995",
            "source": "MANUAL",
        }
        assert latest_prices.calls == [frozenset({f28})]

    def test_an_unknown_instrument_is_404_without_reading_prices(
        self, client: TestClient, latest_prices: FakeLatestPrices
    ) -> None:
        assert client.get(f"/instruments/{uuid4()}").status_code == 404
        assert latest_prices.calls == []

    def test_a_new_instrument_has_none(self, client: TestClient, seeded: Di1Catalogue) -> None:
        body = {"product_id": str(seeded.di1_id), "code": "DI1N27", "maturity_date": "2027-07-01"}

        assert client.post("/instruments", json=body).json()["last_reference"] is None

    def test_decimals_cross_in_plain_notation(
        self, client: TestClient, seeded: Di1Catalogue, latest_prices: FakeLatestPrices
    ) -> None:
        f30 = seeded.instrument_ids["DI1F30"]
        latest_prices.latest[f30] = price(f30, date(2026, 10, 16), "7.5E+4", "1E-1")

        reference = client.get(f"/instruments/{f30}").json()["last_reference"]

        assert (reference["pu"], reference["rate"]) == ("75000", "0.1")
