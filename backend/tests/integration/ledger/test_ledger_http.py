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
from tests.unit.ledger.fakes import DI1F28, DI1F29, DI1V26

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


def test_a_crafted_cursor_is_refused_before_it_reaches_the_database(client: TestClient) -> None:
    record_fixtures(client)
    aware_time = base64.urlsafe_b64encode(b"2026-10-16|10:00:00+03:00|4").decode().rstrip("=")
    huge_seq = base64.urlsafe_b64encode(b"2026-10-16|10:00:00|99999999999999999999").decode()

    for cursor in (aware_time, huge_seq.rstrip("=")):
        response = client.get("/ledger/entries", params={**RANGE, "cursor": cursor})

        assert_problem(response, 422, ("VALIDATION_ERROR", "cursor"))


def test_range_and_search_filter_on_the_server(client: TestClient) -> None:
    record_fixtures(client)

    def seqs(**params: str) -> list[int]:
        response = client.get("/ledger/entries", params={**RANGE, **params})
        assert response.status_code == 200, response.text
        return [item["seq"] for item in response.json()["items"]]

    assert seqs(start_date="2026-10-15", end_date="2026-10-15") == [3]
    assert seqs(search="di1f28") == [4, 2]
    assert seqs(search="Aporte") == [1]
    assert seqs(search="retirada") == [5]
    assert seqs(search="INICIAL") == [1]  # the description (OQ-51)


# --- cash description (OQ-51) -------------------------------------------------------------------

A_DEPOSIT = {"type": "CASH", "date": "2026-10-14", "time": "09:00", "cash_amount": "100.00"}


def test_a_cash_entry_without_a_description_answers_null(client: TestClient) -> None:
    for extra in ({}, {"description": None}, {"description": "   "}):
        response = client.post("/ledger/entries", json={**A_DEPOSIT, **extra})

        assert response.status_code == 201, response.text
        assert response.json()["description"] is None


def test_a_description_of_more_than_200_characters_is_refused(client: TestClient) -> None:
    response = client.post("/ledger/entries", json={**A_DEPOSIT, "description": "a" * 201})

    [error] = assert_problem(response, 422, ("VALIDATION_ERROR", "description"))
    assert error["message"] == "A descrição deve ter no máximo 200 caracteres."
    assert client.get("/ledger/entries", params=RANGE).json()["items"] == []


def test_a_trade_with_a_description_is_refused(client: TestClient) -> None:
    body = {**FIXTURE_REQUESTS[1], "description": "Compra"}

    response = client.post("/ledger/entries", json=body)

    [error] = assert_problem(response, 422, ("VALIDATION_ERROR", "description"))
    assert error["message"] == "Uma operação não tem descrição."


def test_a_nul_character_is_refused_in_a_description_and_finds_nothing(
    client: TestClient,
) -> None:
    response = client.post("/ledger/entries", json={**A_DEPOSIT, "description": "a\u0000b"})

    [error] = assert_problem(response, 422, ("VALIDATION_ERROR", "description"))
    assert error["message"] == "O texto não pode conter o caractere nulo."
    listed = client.get("/ledger/entries", params={**RANGE, "search": "a\u0000"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


def test_a_description_must_be_a_string(client: TestClient) -> None:
    response = client.post("/ledger/entries", json={**A_DEPOSIT, "description": 7})

    assert_problem(response, 422, ("VALIDATION_ERROR", "description"))


# --- deletion -----------------------------------------------------------------------------------


def test_a_batch_deletion_removes_the_entries_and_answers_204(client: TestClient) -> None:
    created = record_fixtures(client)

    response = client.post(
        "/ledger/entries/deletions", json={"ids": [created[4]["id"], created[3]["id"]]}
    )

    assert response.status_code == 204
    assert response.content == b""
    listed = client.get("/ledger/entries", params=RANGE).json()["items"]
    assert [item["seq"] for item in listed] == [3, 2, 1]


def test_deleting_an_entry_twice_answers_404_the_second_time(client: TestClient) -> None:
    created = record_fixtures(client)
    body = {"ids": [created[4]["id"]]}

    assert client.post("/ledger/entries/deletions", json=body).status_code == 204
    assert_problem(client.post("/ledger/entries/deletions", json=body), 404, ("NOT_FOUND", None))


def test_an_unknown_id_answers_404_and_deletes_nothing(client: TestClient) -> None:
    created = record_fixtures(client)

    response = client.post(
        "/ledger/entries/deletions",
        json={"ids": [created[0]["id"], "00000000-0000-4000-8000-000000000000"]},
    )

    errors = assert_problem(response, 404, ("NOT_FOUND", None))
    assert errors[0]["message"] == "Lançamento não encontrado."
    assert len(client.get("/ledger/entries", params=RANGE).json()["items"]) == 5


def test_an_empty_deletion_is_a_validation_error(client: TestClient) -> None:
    response = client.post("/ledger/entries/deletions", json={"ids": []})

    assert_problem(response, 422, ("VALIDATION_ERROR", "ids"))


def test_a_repeated_id_counts_once(client: TestClient) -> None:
    # OQ-32 item 5: {ids: [X, X]} deletes X and succeeds, with no false 404.
    created = record_fixtures(client)
    entry_id = created[4]["id"]

    response = client.post("/ledger/entries/deletions", json={"ids": [entry_id, entry_id]})

    assert response.status_code == 204, response.text
    listed = client.get("/ledger/entries", params=RANGE).json()["items"]
    assert entry_id not in {item["id"] for item in listed}
    assert len(listed) == 4


# --- errors -------------------------------------------------------------------------------------


def test_an_entry_after_today_is_refused_in_portuguese(client: TestClient) -> None:
    response = client.post("/ledger/entries", json={**FIXTURE_REQUESTS[0], "date": "2026-10-19"})

    errors = assert_problem(response, 422, ("FUTURE_DATE", "date"))
    assert errors[0]["message"] == "A data não pode ser posterior a hoje."
    assert response.json()["detail"] == "A data não pode ser posterior a hoje."


def test_an_unknown_contract_is_a_validation_error_on_asset_id(client: TestClient) -> None:
    body = {**FIXTURE_REQUESTS[1], "asset_id": "00000000-0000-4000-8000-000000000000"}

    assert_problem(client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "asset_id"))


def test_too_many_decimals_are_refused_never_rounded(client: TestClient) -> None:
    body = {**FIXTURE_REQUESTS[1], "execution_rate": "0.1000000000001"}

    errors = assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "execution_rate")
    )
    assert errors[0]["message"] == "Use no máximo 12 casas decimais."


def test_a_trade_after_maturity_is_contract_matured(client: TestClient) -> None:
    body = {
        **FIXTURE_REQUESTS[2],
        "asset_id": str(DI1V26.id),
        "date": "2026-10-02",
        "execution_pu": "100000",
    }

    errors = assert_problem(
        client.post("/ledger/entries", json=body), 422, ("CONTRACT_MATURED", "date")
    )
    assert errors[0]["message"] == "O contrato já venceu nesta data."


def test_on_the_maturity_date_the_pu_is_typed_and_the_rate_stored_as_zero(
    client: TestClient,
) -> None:
    closing = {
        **FIXTURE_REQUESTS[2],
        "asset_id": str(DI1V26.id),
        "date": "2026-10-01",
        "execution_pu": "100000.00",
    }
    by_rate = {**FIXTURE_REQUESTS[1], "asset_id": str(DI1V26.id), "date": "2026-10-01"}

    response = client.post("/ledger/entries", json=closing)
    refused = client.post("/ledger/entries", json=by_rate)

    assert response.status_code == 201, response.text
    assert response.json()["execution_pu"] == "100000.00"
    assert response.json()["execution_rate"] == "0.000000000000"
    errors = assert_problem(refused, 422, ("VALIDATION_ERROR", "execution_rate"))
    assert errors[0]["message"] == "Na data de vencimento informe o PU."


def test_a_json_number_for_a_decimal_is_refused(client: TestClient) -> None:
    body = {**FIXTURE_REQUESTS[2], "execution_pu": 82057.0}

    errors = assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "execution_pu")
    )
    assert errors[0]["message"] == "Valor inválido."


def test_non_ascii_digits_in_a_decimal_are_refused(client: TestClient) -> None:
    # Arabic-Indic "123": Decimal() parses it to 123, yet only ASCII [0-9] is a typed decimal.
    body = {**FIXTURE_REQUESTS[2], "execution_pu": "\u0661\u0662\u0663"}

    assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "execution_pu")
    )


@pytest.mark.parametrize("value", ["25:00", "9:00", "10:30:00.5", "", "\u0661\u0660:\u0663\u0660"])
def test_a_malformed_time_is_refused(client: TestClient, value: str) -> None:
    body = {**FIXTURE_REQUESTS[0], "time": value}

    assert_problem(client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "time"))


def test_the_time_is_required(client: TestClient) -> None:
    body = {k: v for k, v in FIXTURE_REQUESTS[0].items() if k != "time"}

    errors = assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "time")
    )
    assert errors[0]["message"] == "Campo obrigatório."


@pytest.mark.parametrize("quantity", [2**31, -(2**31) - 1])
def test_a_quantity_outside_the_integer_column_is_refused(
    client: TestClient, quantity: int
) -> None:
    # signed_quantity is INTEGER: the HTTP schema refuses what the column cannot hold.
    body = {**FIXTURE_REQUESTS[2], "signed_quantity": quantity}

    errors = assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "signed_quantity")
    )
    assert errors[0]["message"] == "Valor inválido."


@pytest.mark.parametrize("field", ["note", "deleted_at"])
def test_an_unknown_body_field_is_refused(client: TestClient, field: str) -> None:
    body = {**FIXTURE_REQUESTS[0], field: "x"}

    assert_problem(client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", field))


def test_a_cash_entry_with_trade_fields_is_refused(client: TestClient) -> None:
    body = {**FIXTURE_REQUESTS[0], "signed_quantity": 1}

    assert_problem(
        client.post("/ledger/entries", json=body), 422, ("VALIDATION_ERROR", "signed_quantity")
    )


def test_a_range_with_start_after_end_is_invalid(client: TestClient) -> None:
    response = client.get(
        "/ledger/entries", params={"start_date": "2026-10-18", "end_date": "2026-10-17"}
    )

    assert_problem(response, 422, ("INVALID_RANGE", "start_date"))


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": "0"}, "limit"),
        ({"limit": "201"}, "limit"),
        ({"cursor": "nope"}, "cursor"),
        ({"order": "sideways"}, "order"),
    ],
)
def test_bad_list_parameters_are_validation_errors(
    client: TestClient, params: dict[str, str], field: str
) -> None:
    response = client.get("/ledger/entries", params={**RANGE, **params})

    assert_problem(response, 422, ("VALIDATION_ERROR", field))


def test_the_range_is_required(client: TestClient) -> None:
    response = client.get("/ledger/entries")

    assert_problem(
        response, 422, ("VALIDATION_ERROR", "start_date"), ("VALIDATION_ERROR", "end_date")
    )


def test_a_rejected_write_leaves_nothing(client: TestClient) -> None:
    response = client.post("/ledger/entries", json={**FIXTURE_REQUESTS[0], "date": "2026-10-19"})

    assert_problem(response, 422, ("FUTURE_DATE", "date"))
    assert client.get("/ledger/entries", params=RANGE).json()["items"] == []
