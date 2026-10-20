"""HTTP and error helpers: a client on a module's routes, and the RFC 9457 problem shape of OQ-15
(``errors[{code, message, field}]``), checked the same way everywhere."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from di1.composition.errors import install_problem_handlers
from di1.shared.errors import DomainError, ErrorCode

PROBLEM_JSON = "application/problem+json"
PROBLEM_KEYS = {"type", "title", "status", "detail", "errors"}


@contextmanager
def app_client(*routers: APIRouter, raise_server_exceptions: bool = True) -> Iterator[TestClient]:
    """A client of a bare app with the composition's problem handlers and ``routers``."""
    app = FastAPI()
    install_problem_handlers(app)
    for router in routers:
        app.include_router(router)
    with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
        yield client


def problem(response: Any, status: int) -> dict[str, Any]:
    """The body of a problem response with ``status``, after checking its shape: the media type,
    the RFC 9457 members, and a pt-BR message on every error."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == PROBLEM_JSON
    body: dict[str, Any] = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert all(e["message"] for e in body["errors"])
    return body


def problem_errors(response: Any, status: int) -> list[tuple[str, str | None]]:
    """The ``(code, field)`` pairs of a problem response with ``status``."""
    return [(e["code"], e["field"]) for e in problem(response, status)["errors"]]


def problem_messages(response: Any, status: int) -> list[tuple[str, str, str | None]]:
    """The ``(code, message, field)`` triples of a problem response with ``status``."""
    return [(e["code"], e["message"], e["field"]) for e in problem(response, status)["errors"]]


def assert_problem(
    response: Any, status: int, *errors: tuple[str, str | None]
) -> list[dict[str, Any]]:
    """Asserts a problem response with ``status`` and exactly ``errors`` as ``(code, field)``, in
    order; returns the errors."""
    body = problem(response, status)
    assert [(e["code"], e["field"]) for e in body["errors"]] == list(errors)
    return list(body["errors"])


def errors_of(caught: pytest.ExceptionInfo[DomainError]) -> list[tuple[ErrorCode, str | None]]:
    """The ``(code, field)`` pairs of a raised `DomainError`, in order."""
    return [(detail.code, detail.field) for detail in caught.value.errors]
