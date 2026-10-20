"""``/ledger/entries`` over HTTP against PostgreSQL: the frozen frontend contract
(frontend/src/api/contract/ledger.ts at 57b4df0) with the MSW fixtures as golden examples
(frontend/src/api/mocks/fixtures.ts at 57b4df0, story of 14 to 16/10/2026, today 18/10/2026).

Rules: interfaces "HTTP endpoints" and "Errors" (problem+json, pt-BR messages, decimals as
strings); spec §6, §11.3, §12; OQ-24 (one route for both types, batch delete all or nothing),
OQ-26 item 1 (keyset pages ``{items, next_cursor}``).
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.composition.errors import install_problem_handlers
from di1.modules.ledger.application.services.ledger_service import LedgerService
from di1.modules.ledger.presentation.http.router import create_router
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from tests.integration.ledger.conftest import ServiceOn
from tests.unit.ledger.fakes import DI1F28, DI1F29

PROBLEM_JSON = "application/problem+json"

# The requests that record the fixtures' ledger, in the order of their seq.
FIXTURE_REQUESTS: list[dict[str, Any]] = [
    {
        "type": "CASH",
        "date": "2026-10-14",
        "time": "09:00",
        "cash_amount": "1500000.00",
        "description": " Aporte inicial ",
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F28.id),
        "date": "2026-10-14",
        "time": "14:10",
        "signed_quantity": 10,
        "input_kind": "RATE",
        "execution_rate": "0.10",
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F29.id),
        "date": "2026-10-15",
        "time": "10:30:00",
        "signed_quantity": 5,
        "input_kind": "PU",
        "execution_pu": "82057.00",
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F28.id),
        "date": "2026-10-16",
        "time": "15:00",
        "signed_quantity": -4,
        "input_kind": "RATE",
        "execution_rate": "0.0995",
    },
    {"type": "CASH", "date": "2026-10-16", "time": "17:30", "cash_amount": "-50000.00"},
]

# fixtures.ts `ledgerEntries`, newest first, without the server-made `id` and `created_at`.
GOLDEN_DESC: list[dict[str, Any]] = [
    {
        "type": "CASH",
        "date": "2026-10-16",
        "time": "17:30:00",
        "seq": 5,
        "cash_amount": "-50000.00",
        "description": None,
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F28.id),
        "asset_code": "DI1F28",
        "instrument_type_code": "FUTURE",
        "date": "2026-10-16",
        "time": "15:00:00",
        "seq": 4,
        "signed_quantity": -4,
        "execution_pu": "89102.2226533433",
        "execution_rate": "0.0995",
        "input_kind": "RATE",
        "cash_amount": "356408.8906133732",
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F29.id),
        "asset_code": "DI1F29",
        "instrument_type_code": "FUTURE",
        "date": "2026-10-15",
        "time": "10:30:00",
        "seq": 3,
        "signed_quantity": 5,
        "execution_pu": "82057.00",
        "execution_rate": "0.093203413834",
        "input_kind": "PU",
        "cash_amount": "-410285.00",
    },
    {
        "type": "TRADE",
        "asset_id": str(DI1F28.id),
        "asset_code": "DI1F28",
        "instrument_type_code": "FUTURE",
        "date": "2026-10-14",
        "time": "14:10:00",
        "seq": 2,
        "signed_quantity": 10,
        "execution_pu": "89006.4625467350",
        "execution_rate": "0.10",
        "input_kind": "RATE",
        "cash_amount": "-890064.6254673500",
    },
    {
        "type": "CASH",
        "date": "2026-10-14",
        "time": "09:00:00",
        "seq": 1,
        "cash_amount": "1500000.00",
        "description": "Aporte inicial",
    },
]

RANGE = {"start_date": "2026-10-01", "end_date": "2026-10-18"}


@pytest.fixture
def client(
    service: ServiceOn, session_factory: async_sessionmaker[AsyncSession]
) -> Iterator[TestClient]:
    async def unit_of_work() -> AsyncIterator[UnitOfWork]:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    def ledger_service(uow: UnitOfWork = Depends(unit_of_work)) -> LedgerService:  # noqa: B008
        return service(uow)

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(create_router(get_service=ledger_service))
    with TestClient(app) as test_client:
        yield test_client


def record_fixtures(client: TestClient) -> list[dict[str, Any]]:
    created = []
    for body in FIXTURE_REQUESTS:
        response = client.post("/ledger/entries", json=body)
        assert response.status_code == 201, response.text
        created.append(response.json())
    return created


def without_server_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in {"id", "created_at"}}


def assert_problem(response: Any, status: int, *errors: tuple[str, str | None]) -> list[Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["status"] == status
    assert [(e["code"], e["field"]) for e in body["errors"]] == list(errors)
    return list(body["errors"])


# --- golden shapes ------------------------------------------------------------------------------


def test_the_fixtures_ledger_reads_back_exactly(client: TestClient) -> None:
    created = record_fixtures(client)

    response = client.get("/ledger/entries", params=RANGE)

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert [without_server_fields(item) for item in body["items"]] == GOLDEN_DESC
    assert [item["id"] for item in body["items"]] == [c["id"] for c in reversed(created)]


def test_a_created_entry_is_answered_in_the_list_shape(client: TestClient) -> None:
    created = record_fixtures(client)

    assert [without_server_fields(c) for c in created] == GOLDEN_DESC[::-1]
    trade = created[1]
    assert set(trade) == {
        "id", "type", "date", "time", "seq", "cash_amount", "created_at", "asset_id",
        "asset_code", "instrument_type_code", "signed_quantity", "execution_pu",
        "execution_rate", "input_kind",
    }  # fmt: skip
    assert set(created[0]) == {
        "id", "type", "date", "time", "seq", "cash_amount", "created_at", "description",
    }  # fmt: skip
    # An instant in UTC ("Z"), like every other module's timestamps (processing's _utc).
    assert all(c["created_at"].endswith("Z") for c in created)


def test_ascending_order_is_the_exact_reverse(client: TestClient) -> None:
    record_fixtures(client)

    response = client.get("/ledger/entries", params={**RANGE, "order": "asc"})

    assert [without_server_fields(i) for i in response.json()["items"]] == GOLDEN_DESC[::-1]


def test_pages_follow_the_cursor(client: TestClient) -> None:
    record_fixtures(client)

    first = client.get("/ledger/entries", params={**RANGE, "limit": 2}).json()
    second = client.get(
        "/ledger/entries", params={**RANGE, "limit": 2, "cursor": first["next_cursor"]}
    ).json()
    third = client.get(
        "/ledger/entries", params={**RANGE, "limit": 2, "cursor": second["next_cursor"]}
    ).json()

    seqs = [[i["seq"] for i in page["items"]] for page in (first, second, third)]
    assert seqs == [[5, 4], [3, 2], [1]]
    assert third["next_cursor"] is None


def test_an_empty_cursor_is_the_first_page(client: TestClient) -> None:
    record_fixtures(client)

    response = client.get("/ledger/entries", params={**RANGE, "limit": 2, "cursor": ""})

    assert response.status_code == 200, response.text
    assert [item["seq"] for item in response.json()["items"]] == [5, 4]


def test_range_and_search_reach_the_server(client: TestClient) -> None:
    # The search itself is SQL (test_ledger_persistence); here only the query parameters.
    record_fixtures(client)

    def seqs(**params: str) -> list[int]:
        response = client.get("/ledger/entries", params={**RANGE, **params})
        assert response.status_code == 200, response.text
        return [item["seq"] for item in response.json()["items"]]

    assert seqs(start_date="2026-10-15", end_date="2026-10-15") == [3]
    assert seqs(search="di1f28") == [4, 2]
    assert seqs(search="INICIAL") == [1]  # the description (OQ-51)


def test_a_search_with_a_nul_character_answers_an_empty_page(client: TestClient) -> None:
    record_fixtures(client)

    listed = client.get("/ledger/entries", params={**RANGE, "search": "a\u0000"})

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


# --- cash description (OQ-51) -------------------------------------------------------------------

A_DEPOSIT = {"type": "CASH", "date": "2026-10-14", "time": "09:00", "cash_amount": "100.00"}


def test_a_cash_entry_without_a_description_answers_null(client: TestClient) -> None:
    for extra in ({}, {"description": None}, {"description": "   "}):
        response = client.post("/ledger/entries", json={**A_DEPOSIT, **extra})

        assert response.status_code == 201, response.text
        assert response.json()["description"] is None


# --- deletion -----------------------------------------------------------------------------------
# All or nothing, 404 for an unknown or deleted id and a repeated id are spec §13 item 16
# (acceptance/test_ledger_http.py) and SQL (test_ledger_persistence.py).


def test_a_batch_deletion_removes_the_entries_and_answers_204(client: TestClient) -> None:
    created = record_fixtures(client)

    response = client.post(
        "/ledger/entries/deletions", json={"ids": [created[4]["id"], created[3]["id"]]}
    )

    assert response.status_code == 204
    assert response.content == b""
    listed = client.get("/ledger/entries", params=RANGE).json()["items"]
    assert [item["seq"] for item in listed] == [3, 2, 1]


def test_an_empty_deletion_is_a_validation_error(client: TestClient) -> None:
    response = client.post("/ledger/entries/deletions", json={"ids": []})

    assert_problem(response, 422, ("VALIDATION_ERROR", "ids"))


# --- errors -------------------------------------------------------------------------------------
# Each rule and its pt-BR message is tested once against the domain (tests/unit/ledger); here
# only the status and the problem's (code, field), plus the messages the HTTP layer writes.

_TRADE_BY_PU = FIXTURE_REQUESTS[2]
_UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
_NO_TIME = {k: v for k, v in FIXTURE_REQUESTS[0].items() if k != "time"}


@pytest.mark.parametrize(
    ("body", "errors", "message"),
    [
        pytest.param(
            {**FIXTURE_REQUESTS[0], "date": "2026-10-19"},
            [("FUTURE_DATE", "date")],
            None,
            id="future-date",
        ),
        pytest.param(
            {**FIXTURE_REQUESTS[1], "asset_id": _UNKNOWN_ID},
            [("VALIDATION_ERROR", "asset_id")],  # a body field never answers 404
            None,
            id="unknown-contract",
        ),
        pytest.param(
            {**_TRADE_BY_PU, "execution_pu": 82057.0},
            [("VALIDATION_ERROR", "execution_pu")],
            "Valor inválido.",
            id="json-number-decimal",
        ),
        # Arabic-Indic "123": Decimal() parses it to 123, yet only ASCII [0-9] is a typed decimal.
        pytest.param(
            {**_TRADE_BY_PU, "execution_pu": "\u0661\u0662\u0663"},
            [("VALIDATION_ERROR", "execution_pu")],
            None,
            id="non-ascii-digits",
        ),
        *(
            pytest.param(
                {**FIXTURE_REQUESTS[0], "time": value},
                [("VALIDATION_ERROR", "time")],
                None,
                id=f"time-{name}",
            )
            for name, value in (
                ("25h", "25:00"),
                ("one-digit-hour", "9:00"),
                ("fraction", "10:30:00.5"),
                ("empty", ""),
                ("non-ascii", "\u0661\u0660:\u0663\u0660"),
            )
        ),
        pytest.param(_NO_TIME, [("VALIDATION_ERROR", "time")], "Campo obrigatório.", id="no-time"),
        # signed_quantity is INTEGER: out of its range is the domain's 422, reported with the
        # other errors, never a database error.
        *(
            pytest.param(
                {**_TRADE_BY_PU, "signed_quantity": quantity, "date": "2026-10-19"},
                [("FUTURE_DATE", "date"), ("VALIDATION_ERROR", "signed_quantity")],
                None,
                id=f"quantity-{name}",
            )
            for name, quantity in (("above-int", 2**31), ("below-int", -(2**31) - 1))
        ),
        *(
            pytest.param(
                {**FIXTURE_REQUESTS[0], field: "x"},
                [("VALIDATION_ERROR", field)],
                None,
                id=f"unknown-field-{field}",
            )
            for field in ("note", "deleted_at")
        ),
        pytest.param(
            {**FIXTURE_REQUESTS[0], "signed_quantity": 1},
            [("VALIDATION_ERROR", "signed_quantity")],
            None,
            id="cash-with-trade-field",
        ),
        pytest.param(
            {**A_DEPOSIT, "description": "a" * 201},
            [("VALIDATION_ERROR", "description")],
            None,
            id="description-too-long",
        ),
        pytest.param(
            {**FIXTURE_REQUESTS[1], "description": "Compra"},
            [("VALIDATION_ERROR", "description")],
            None,
            id="trade-with-description",
        ),
        pytest.param(
            {**A_DEPOSIT, "description": "a\u0000b"},
            [("VALIDATION_ERROR", "description")],
            None,
            id="description-nul",
        ),
        pytest.param(
            {**A_DEPOSIT, "description": 7},
            [("VALIDATION_ERROR", "description")],
            None,
            id="description-not-a-string",
        ),
    ],
)
def test_a_refused_entry_answers_a_problem(
    client: TestClient,
    body: dict[str, Any],
    errors: list[tuple[str, str]],
    message: str | None,
) -> None:
    response = client.post("/ledger/entries", json=body)

    first = assert_problem(response, 422, *errors)[0]
    if message is not None:
        assert first["message"] == message


def test_a_rejected_write_leaves_nothing(client: TestClient) -> None:
    response = client.post("/ledger/entries", json={**FIXTURE_REQUESTS[0], "date": "2026-10-19"})

    [error] = assert_problem(response, 422, ("FUTURE_DATE", "date"))
    # A single error's pt-BR message is also the problem's detail.
    assert response.json()["detail"] == error["message"] == "A data não pode ser posterior a hoje."
    assert client.get("/ledger/entries", params=RANGE).json()["items"] == []


def _cursor(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    ("params", "errors"),
    [
        pytest.param(
            {"start_date": "2026-10-18", "end_date": "2026-10-17"},
            [("INVALID_RANGE", "start_date")],
            id="start-after-end",
        ),
        pytest.param(
            {},
            [("VALIDATION_ERROR", "start_date"), ("VALIDATION_ERROR", "end_date")],
            id="no-range",
        ),
        pytest.param({**RANGE, "cursor": "nope"}, [("VALIDATION_ERROR", "cursor")], id="cursor"),
        # Crafted cursors are refused before they reach the database, never a server error.
        pytest.param(
            {**RANGE, "cursor": _cursor("2026-10-16|10:00:00+03:00|4")},
            [("VALIDATION_ERROR", "cursor")],
            id="cursor-aware-time",
        ),
        pytest.param(
            {**RANGE, "cursor": _cursor("2026-10-16|10:00:00|99999999999999999999")},
            [("VALIDATION_ERROR", "cursor")],
            id="cursor-beyond-bigint",
        ),
        pytest.param({**RANGE, "order": "sideways"}, [("VALIDATION_ERROR", "order")], id="order"),
        # limit=0 and limit=201 are spec §13 item 22 (acceptance/test_ledger_http.py).
    ],
)
def test_bad_list_parameters_answer_a_problem(
    client: TestClient, params: dict[str, str], errors: list[tuple[str, str]]
) -> None:
    record_fixtures(client)

    assert_problem(client.get("/ledger/entries", params=params), 422, *errors)
