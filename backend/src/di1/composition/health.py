"""``GET /health`` (and ``HEAD``): the process is up and PostgreSQL answers (X3).

200 ``{"status": "ok"}`` when ``SELECT 1`` succeeds within ``app.state.health_timeout`` seconds;
otherwise 503 problem+json, with nothing of the database error in the body. The timeout also
bounds the wait for a pooled connection, so a hung database or an exhausted pool answers 503
instead of holding the probe. The failure is logged without a traceback: a probe repeats often.
"""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.composition.errors import problem_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> JSONResponse:
    engine: AsyncEngine = request.app.state.engine
    timeout: float = request.app.state.health_timeout
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        logger.warning("health check: the database did not answer (%s)", type(error).__name__)
        status = HTTPStatus.SERVICE_UNAVAILABLE
        return problem_response(status, "O banco de dados não está acessível.")
    return JSONResponse({"status": "ok"})
