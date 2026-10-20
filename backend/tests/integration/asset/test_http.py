"""Asset HTTP routes against PostgreSQL 16, through the real app (interfaces.md "HTTP endpoints";
OQ-26 item 8: the shapes of ``frontend/src/api/contract/asset.ts``).

The MSW fixtures (``frontend/src/api/mocks/fixtures.ts``) are the golden examples of the shapes:
field names, decimals as strings, ``null`` rather than 0. Server-generated values (product and
instrument ids, ``created_at``) are compared by type only. ``last_reference`` is each instrument's
latest winning reference price from `prices.public.PriceReader.latest`
(OQ-48), ``null`` when it has none; a fake reader stands in for Prices.
Errors are problem+json (OQ-15) with pt-BR messages: one table of refused writes shows how each
kind of problem reaches the client (the rules: ``tests/unit/asset/test_rules.py``; duplicates,
lookups and what is written: ``test_asset_service.py``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from di1.composition.dependencies import get_asset_service
from di1.main import create_app
from di1.modules.asset.presentation.http.router import create_router
from di1.modules.prices.public import PriceSource
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from tests.integration.asset.conftest import Di1Catalogue, seed_di1
from tests.integration.asset.latest_prices import FakePriceReader, price

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
def latest_prices() -> FakePriceReader:
    """No instrument has a price unless a test gives it one."""
    return FakePriceReader()


@pytest.fixture
def client(
    settings: Settings, seeded: Di1Catalogue, latest_prices: FakePriceReader
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.include_router(
        create_router(get_service=get_asset_service, get_price_reader=lambda: latest_prices)
    )
    with TestClient(app) as client:
        yield client


def _problem(response: Any) -> tuple[int, str, list[tuple[str, str, str | None]]]:
    body = response.json()
    assert body["type"] == "about:blank"
    errors = [(e["code"], e["message"], e["field"]) for e in body["errors"]]
    return response.status_code, response.headers["content-type"], errors


PROBLEM = "application/problem+json"


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


def test_instrument_types_are_listed_with_their_classes(client: TestClient) -> None:
    response = client.get("/instrument-types")

    assert (response.status_code, response.json()) == (200, GOLDEN_INSTRUMENT_TYPES)


def test_products_are_listed_in_the_contract_shape(
    client: TestClient, seeded: Di1Catalogue
) -> None:
    body = client.get("/products").json()

    assert list(body) == ["items"]
    (product,) = body["items"]
    assert product == _with_generated(GOLDEN_PRODUCT, product)
    assert product["id"] == str(seeded.di1_id)


def test_one_product_is_read_in_the_contract_shape(
    client: TestClient, seeded: Di1Catalogue
) -> None:
    response = client.get(f"/products/{seeded.di1_id}")

    assert response.status_code == 200
    assert response.json() == _with_generated(GOLDEN_PRODUCT, response.json())


def test_instruments_are_listed_by_maturity_in_the_contract_shape(
    client: TestClient, seeded: Di1Catalogue
) -> None:
    body = client.get("/instruments", params={"product_id": str(seeded.di1_id)}).json()

    assert list(body) == ["items"]
    assert body["items"] == [
        _with_generated(golden, actual)
        for golden, actual in zip(GOLDEN_INSTRUMENTS, body["items"], strict=True)
    ]
    assert [i["product_id"] for i in body["items"]] == [str(seeded.di1_id)] * 4


def test_one_instrument_is_read_in_the_contract_shape(
    client: TestClient, seeded: Di1Catalogue
) -> None:
    response = client.get(f"/instruments/{seeded.instrument_ids['DI1F28']}")

    assert response.status_code == 200
    assert response.json() == _with_generated(GOLDEN_INSTRUMENTS[1], response.json())


def test_creating_an_instrument_answers_201_with_it(
    client: TestClient, seeded: Di1Catalogue
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


def test_creating_a_product_answers_201_with_it(client: TestClient, seeded: Di1Catalogue) -> None:
    """``POST /products`` (interfaces.md "HTTP endpoints"); not used by the current UI."""
    body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "code": " dap "}

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


def test_the_multiplier_defaults_to_one(client: TestClient, seeded: Di1Catalogue) -> None:
    futures = {"face_value": "100000", "settlement_method": "CASH"}
    body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "futures": futures}

    created = client.post("/products", json=body).json()

    assert created["futures"] == {
        "face_value": "100000",
        "contract_multiplier": "1",
        "settlement_method": "CASH",
        "settlement_description": None,
    }


@pytest.mark.parametrize(
    ("instrument_type", "codes"),
    [("FUTURE", ["DI1"]), ("OPTION", []), ("", ["DI1"]), ("\x00", [])],
    ids=["future", "option", "empty", "nul"],
)
def test_products_are_filtered_by_the_type_query(
    client: TestClient, instrument_type: str, codes: list[str]
) -> None:
    # Search over HTTP: tests/integration/acceptance/test_catalogue_http.py.
    response = client.get("/products", params={"instrument_type": instrument_type})

    assert response.status_code == 200
    assert [p["code"] for p in response.json()["items"]] == codes


@pytest.mark.parametrize(
    ("resource", "message"),
    [("products", "Produto não encontrado."), ("instruments", "Contrato não encontrado.")],
)
def test_an_unknown_product_or_instrument_is_404(
    client: TestClient, resource: str, message: str
) -> None:
    assert _problem(client.get(f"/{resource}/{uuid4()}")) == (
        404,
        PROBLEM,
        [("NOT_FOUND", message, None)],
    )


def test_a_malformed_path_id_is_422(client: TestClient) -> None:
    assert _problem(client.get("/instruments/not-a-uuid"))[0] == 422


Body = Callable[[Di1Catalogue], dict[str, Any]]


def _instrument(**fields: Any) -> Body:
    return lambda seeded: {"product_id": str(seeded.di1_id), "code": "DI1N27"} | fields


def _product(**fields: Any) -> Body:
    return lambda seeded: DAP | {"asset_class_id": seeded.interest_rate_class_id} | fields


NUL_MESSAGE = "O texto não pode conter o caractere nulo."


@pytest.mark.parametrize(
    ("path", "body", "errors"),
    [
        pytest.param(
            # The field is required (contract CreateInstrumentRequest); null is allowed only for
            # a product that is not a future (spec §3).
            "/instruments",
            _instrument(),
            [("VALIDATION_ERROR", "Campo obrigatório.", "maturity_date")],
            id="maturity-absent",
        ),
        pytest.param(
            "/instruments",
            _instrument(maturity_date=None),
            [("VALIDATION_ERROR", "Informe o vencimento.", "maturity_date")],
            id="maturity-null-on-a-future",
        ),
        pytest.param(
            "/instruments",
            _instrument(code="DI1\u0000N27", maturity_date="2027-07-01"),
            [("VALIDATION_ERROR", NUL_MESSAGE, "code")],
            id="nul-in-code",
        ),
        pytest.param(
            "/instruments",
            lambda _: {"product_id": "x", "maturity_date": "2027-13-01"},
            [
                ("VALIDATION_ERROR", "Campo obrigatório.", "code"),
                ("VALIDATION_ERROR", "Valor inválido.", "maturity_date"),
                ("VALIDATION_ERROR", "Valor inválido.", "product_id"),
            ],
            id="malformed-instrument",
        ),
        pytest.param(
            "/instruments",
            _instrument(maturity_date=None, unknown=1),
            [("VALIDATION_ERROR", "Valor inválido.", "unknown")],
            id="unknown-instrument-field",
        ),
        pytest.param(
            "/products",
            lambda seeded: {
                "asset_class_id": seeded.interest_rate_class_id,
                "code": "DAP",
                "name": "Cupom",
            },
            [("VALIDATION_ERROR", "Informe a especificação do contrato futuro.", "futures")],
            id="future-without-futures",
        ),
        # Unknown classes in and out of the SMALLINT range: test_asset_service.py; 999 over
        # HTTP: tests/integration/acceptance/test_catalogue_http.py.
        *(
            pytest.param(
                "/products",
                _product(asset_class_id=asset_class_id),
                [("VALIDATION_ERROR", "Classe de ativo não encontrada.", "asset_class_id")],
                id=f"unknown-class-{asset_class_id}",
            )
            for asset_class_id in (0, 10**12)
        ),
        pytest.param(
            "/products",
            _product(unknown=1),
            [("VALIDATION_ERROR", "Valor inválido.", "unknown")],
            id="unknown-product-field",
        ),
    ],
)
def test_a_refused_write_is_a_422_problem(
    client: TestClient,
    seeded: Di1Catalogue,
    path: str,
    body: Body,
    errors: list[tuple[str, str, str]],
) -> None:
    status, content_type, actual = _problem(client.post(path, json=body(seeded)))

    assert (status, content_type) == (422, PROBLEM)
    assert sorted(actual, key=lambda e: e[2] or "") == errors


@pytest.mark.parametrize("face_value", [100000, 1.5, "1e5", "Infinity", "NaN", "", "1,5"])
def test_decimals_are_plain_decimal_strings(
    client: TestClient, seeded: Di1Catalogue, face_value: object
) -> None:
    futures = dict(DAP["futures"]) | {"face_value": face_value}  # type: ignore[arg-type]
    body = DAP | {"asset_class_id": seeded.interest_rate_class_id, "futures": futures}

    status, _, errors = _problem(client.post("/products", json=body))

    assert (status, [e[2] for e in errors]) == (422, ["futures.face_value"])


# ``Instrument.last_reference`` (OQ-48, reversing OQ-33 item 4): the latest preferred price, with
# its own date (OQ-19 item 5); ``null`` for an instrument without one.


def test_each_listed_instrument_carries_its_latest_price(
    client: TestClient, seeded: Di1Catalogue, latest_prices: FakePriceReader
) -> None:
    f28, f29 = seeded.instrument_ids["DI1F28"], seeded.instrument_ids["DI1F29"]
    latest_prices.by_asset[f28] = price(f28, date(2026, 10, 16), "89102.2226533433", "0.0995")
    latest_prices.by_asset[f29] = price(
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
    client: TestClient, seeded: Di1Catalogue, latest_prices: FakePriceReader
) -> None:
    client.get("/instruments", params={"search": "f2"})

    assert latest_prices.calls == [
        frozenset(seeded.instrument_ids[c] for c in ("DI1F27", "DI1F28", "DI1F29"))
    ]


def test_an_empty_listing_reads_no_prices(
    client: TestClient, latest_prices: FakePriceReader
) -> None:
    assert client.get("/instruments", params={"search": "x"}).json() == {"items": []}
    assert latest_prices.calls == []


def test_one_instrument_carries_its_latest_price(
    client: TestClient, seeded: Di1Catalogue, latest_prices: FakePriceReader
) -> None:
    f28 = seeded.instrument_ids["DI1F28"]
    latest_prices.by_asset[f28] = price(f28, date(2026, 10, 16), "89102.2226533433", "0.0995")

    body = client.get(f"/instruments/{f28}").json()

    assert body["last_reference"] == {
        "reference_date": "2026-10-16",
        "pu": "89102.2226533433",
        "rate": "0.0995",
        "source": "MANUAL",
    }
    assert latest_prices.calls == [frozenset({f28})]


def test_an_unknown_instrument_is_404_without_reading_prices(
    client: TestClient, latest_prices: FakePriceReader
) -> None:
    assert client.get(f"/instruments/{uuid4()}").status_code == 404
    assert latest_prices.calls == []


def test_a_new_instrument_has_no_latest_price(client: TestClient, seeded: Di1Catalogue) -> None:
    body = {"product_id": str(seeded.di1_id), "code": "DI1N27", "maturity_date": "2027-07-01"}

    assert client.post("/instruments", json=body).json()["last_reference"] is None


def test_the_latest_price_crosses_in_plain_notation(
    client: TestClient, seeded: Di1Catalogue, latest_prices: FakePriceReader
) -> None:
    f30 = seeded.instrument_ids["DI1F30"]
    latest_prices.by_asset[f30] = price(f30, date(2026, 10, 16), "7.5E+4", "1E-1")

    reference = client.get(f"/instruments/{f30}").json()["last_reference"]

    assert (reference["pu"], reference["rate"]) == ("75000", "0.1")
