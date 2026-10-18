"""Every error response is RFC 9457 problem+json (OQ-15; interfaces.md "Errors")."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from di1.composition.errors import PROBLEM_JSON, STATUS_BY_CODE, install_problem_handlers
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail


def _app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/future")
    async def future() -> None:
        raise DomainError(
            ErrorDetail(
                ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "trade_date"
            ),
            detail="Lançamento recusado.",
        )

    @app.get("/finished")
    async def finished() -> None:
        raise DomainError(
            ErrorDetail(ErrorCode.JOB_NOT_CANCELLABLE, "O processamento já terminou.")
        )

    @app.get("/mixed")
    async def mixed() -> None:
        raise DomainError(
            ErrorDetail(ErrorCode.VALIDATION_ERROR, "Valor inválido.", "quantity"),
            ErrorDetail(ErrorCode.NOT_FOUND, "Ativo não encontrado.", "instrument_id"),
        )

    @app.get("/typed")
    async def typed(start_date: date, quantity: int) -> None:
        return None

    @app.post("/body")
    async def body(payload: dict[str, int]) -> None:
        return None

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal state")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def _problem(response: Any, status: int, title: str, detail: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["title"] == title
    assert body["detail"] == detail
    return body


def test_every_catalogue_code_has_the_documented_status() -> None:
    assert {code.value: status for code, status in STATUS_BY_CODE.items()} == {
        "VALIDATION_ERROR": 422,
        "FUTURE_DATE": 422,
        "CONTRACT_MATURED": 422,
        "NOT_FOUND": 404,
        "INVALID_RANGE": 422,
        "JOB_NOT_CANCELLABLE": 409,
    }


def test_a_domain_error_becomes_a_problem_with_its_details(client: TestClient) -> None:
    body = _problem(client.get("/future"), 422, "Dados inválidos", "Lançamento recusado.")

    assert body["errors"] == [
        {
            "code": "FUTURE_DATE",
            "message": "A data não pode ser posterior a hoje.",
            "field": "trade_date",
        }
    ]


def test_the_status_follows_the_code(client: TestClient) -> None:
    body = _problem(client.get("/finished"), 409, "Conflito", "O processamento já terminou.")

    assert body["errors"] == [
        {"code": "JOB_NOT_CANCELLABLE", "message": "O processamento já terminou.", "field": None}
    ]


def test_invalid_query_parameters_are_validation_errors_per_field(client: TestClient) -> None:
    response = client.get("/typed", params={"start_date": "31/12/2026"})
    body = _problem(response, 422, "Dados inválidos", "A requisição contém dados inválidos.")

    assert body["errors"] == [
        {"code": "VALIDATION_ERROR", "message": "Valor inválido.", "field": "start_date"},
        {"code": "VALIDATION_ERROR", "message": "Campo obrigatório.", "field": "quantity"},
    ]


def test_a_body_field_is_named_without_the_body_prefix(client: TestClient) -> None:
    response = client.post("/body", json={"quantity": "many"})
    body = _problem(response, 422, "Dados inválidos", "A requisição contém dados inválidos.")

    assert body["errors"] == [
        {"code": "VALIDATION_ERROR", "message": "Valor inválido.", "field": "quantity"}
    ]


def test_malformed_json_is_a_validation_error_without_a_field(client: TestClient) -> None:
    response = client.post("/body", content=b"{", headers={"content-type": "application/json"})
    body = _problem(response, 422, "Dados inválidos", "A requisição contém dados inválidos.")

    assert body["errors"] == [
        {"code": "VALIDATION_ERROR", "message": "JSON inválido.", "field": None}
    ]


def test_an_unknown_route_is_not_found(client: TestClient) -> None:
    response = client.get("/nowhere")
    body = _problem(response, 404, "Recurso não encontrado", "Recurso não encontrado.")

    assert body["errors"] == [
        {"code": "NOT_FOUND", "message": "Recurso não encontrado.", "field": None}
    ]


def test_a_wrong_method_keeps_the_allow_header_and_has_no_catalogue_code(
    client: TestClient,
) -> None:
    response = client.delete("/future")
    body = _problem(
        response, 405, "Método não permitido", "Método não permitido para este recurso."
    )

    assert response.headers["allow"] == "GET"
    assert body["errors"] == []


def test_an_unexpected_error_is_a_500_that_hides_the_exception(client: TestClient) -> None:
    response = client.get("/boom")
    body = _problem(response, 500, "Erro interno", "Ocorreu um erro interno. Tente novamente.")

    for leaked in ("secret", "RuntimeError", "Traceback"):
        assert leaked not in response.text
    assert body["errors"] == []


def test_details_of_different_statuses_are_a_500_not_an_order_dependent_status(
    client: TestClient,
) -> None:
    response = client.get("/mixed")
    body = _problem(response, 500, "Erro interno", "Ocorreu um erro interno. Tente novamente.")

    assert body["errors"] == []
