"""RFC 9457 ``application/problem+json`` for every error response (OQ-15; interfaces.md "Errors").

Body: ``{"type": "about:blank", "title", "status", "detail", "errors": [{code, message, field}]}``.
``title``, ``detail`` and every ``message`` are pt-BR; ``code`` is English. ``errors`` is always
present, and empty when no catalogue code applies (a wrong method, an unexpected failure).

Mapped here, once for the whole API:

- `DomainError` → the status of its codes (`STATUS_BY_CODE`); details whose codes map to
  different statuses are a programming error and answer 500;
- request validation (FastAPI/Pydantic) → 422 ``VALIDATION_ERROR``, one entry per field;
- an HTTP error raised by routing → its status, ``NOT_FOUND`` for 404;
- anything else → 500, with nothing of the exception in the body.

Business codes (``FUTURE_DATE``, ``CONTRACT_MATURED``, too many decimals as
``VALIDATION_ERROR``, ...) are raised only as a `DomainError` from ``application/`` or
``domain/``; routers raise no errors of their own, and never ``HTTPException``, whose
``detail`` is replaced by the generic one. Pydantic schemas check syntax only: a message raised
inside a Pydantic validator is replaced by the generic "Valor inválido.".
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

STATUS_BY_CODE: Mapping[ErrorCode, HTTPStatus] = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.FUTURE_DATE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.CONTRACT_MATURED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.INVALID_RANGE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.JOB_NOT_CANCELLABLE: HTTPStatus.CONFLICT,
}

_TITLES: Mapping[int, str] = {
    400: "Requisição inválida",
    404: "Recurso não encontrado",
    405: "Método não permitido",
    409: "Conflito",
    422: "Dados inválidos",
    500: "Erro interno",
    503: "Serviço indisponível",
}
_DETAILS: Mapping[int, str] = {
    404: "Recurso não encontrado.",
    405: "Método não permitido para este recurso.",
    422: "A requisição contém dados inválidos.",
    500: "Ocorreu um erro interno. Tente novamente.",
}
# Where FastAPI says the invalid value came from; the client names the field without it.
_LOCATIONS = frozenset({"body", "query", "path", "header", "cookie"})


def _title(status: int) -> str:
    return _TITLES.get(status, "Erro na requisição" if status < 500 else "Erro interno")


def _detail(status: int) -> str:
    return _DETAILS.get(status, f"{_title(status)}.")


def problem_response(
    status: int,
    detail: str,
    errors: Sequence[ErrorDetail] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """A problem+json response; every handler in this module goes through it."""
    body = {
        "type": "about:blank",
        "title": _title(status),
        "status": status,
        "detail": detail,
        "errors": [
            {"code": error.code.value, "message": error.message, "field": error.field}
            for error in errors
        ],
    }
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


def _validation_detail(error: Mapping[str, Any]) -> ErrorDetail:
    location = tuple(str(part) for part in error.get("loc", ()))
    if error.get("type") == "json_invalid":
        return ErrorDetail.validation("JSON inválido.")
    if location and location[0] in _LOCATIONS:
        location = location[1:]
    message = "Campo obrigatório." if error.get("type") == "missing" else "Valor inválido."
    return ErrorDetail.validation(message, ".".join(location) or None)


def _expect[E: Exception](exc: Exception, kind: type[E]) -> E:
    if not isinstance(exc, kind):
        raise TypeError(f"{kind.__name__} handler received {type(exc).__name__}")
    return exc


async def _on_domain_error(_: Request, exc: Exception) -> JSONResponse:
    error = _expect(exc, DomainError)
    statuses = {STATUS_BY_CODE[detail.code] for detail in error.errors}
    if len(statuses) != 1:
        logger.error(
            "DomainError mixes codes of different statuses: %s", error.errors, exc_info=error
        )
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        return problem_response(status, _detail(status))
    status = statuses.pop()
    detail = error.detail if error.detail is not None else _detail(status)
    return problem_response(status, detail, error.errors)


async def _on_validation_error(_: Request, exc: Exception) -> JSONResponse:
    exc = _expect(exc, RequestValidationError)
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    errors = [_validation_detail(error) for error in exc.errors()]
    return problem_response(status, _detail(status), errors)


async def _on_http_error(_: Request, exc: Exception) -> JSONResponse:
    exc = _expect(exc, StarletteHTTPException)
    status = exc.status_code
    errors = (
        [ErrorDetail(ErrorCode.NOT_FOUND, "Recurso não encontrado.")]
        if status == HTTPStatus.NOT_FOUND
        else []
    )
    return problem_response(status, _detail(status), errors, exc.headers)


async def _on_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    # Starlette's ServerErrorMiddleware re-raises ``exc`` after this response is sent, so the
    # server logs the traceback once; logging it here too would duplicate it.
    status = HTTPStatus.INTERNAL_SERVER_ERROR
    return problem_response(status, _detail(status))


def install_problem_handlers(app: FastAPI) -> None:
    """Register the handlers on ``app``; ``main.py`` calls this once when it builds the app."""
    app.add_exception_handler(DomainError, _on_domain_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(Exception, _on_unexpected_error)
