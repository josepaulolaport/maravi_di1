"""The application factory (X3): problem+json everywhere, a health check that fails safely and
quickly, and the engine disposed at shutdown.

No database is needed: the engine connects lazily, so an unreachable or silent server only matters
to ``/health``, which must answer 503 problem+json without leaking the error.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.composition.errors import PROBLEM_JSON
from di1.main import create_app
from di1.platform.config import Settings

UNREACHABLE = Settings(
    database_url=SecretStr("postgresql+psycopg://di1:secret-password@127.0.0.1:1/di1")
)


@pytest.fixture
def silent_server() -> Iterator[int]:
    """A TCP port that accepts connections and never answers, like a hung database."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield listener.getsockname()[1]


def test_health_is_a_503_problem_when_the_database_does_not_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG), TestClient(create_app(UNREACHABLE)) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["title"] == "Serviço indisponível"
    assert body["detail"] == "O banco de dados não está acessível."
    assert body["errors"] == []
    for leaked in ("secret-password", "127.0.0.1", "OperationalError"):
        assert leaked not in response.text
    assert "secret-password" not in caplog.text


def test_a_hung_database_answers_503_within_the_timeout(silent_server: int) -> None:
    hung = Settings(
        database_url=SecretStr(f"postgresql+psycopg://di1:x@127.0.0.1:{silent_server}/di1")
    )
    with TestClient(create_app(hung, health_timeout=0.5)) as client:
        started = time.monotonic()
        response = client.get("/health")
        elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert elapsed < 3


def test_head_is_answered_like_get() -> None:
    with TestClient(create_app(UNREACHABLE)) as client:
        response = client.head("/health")

    assert response.status_code == 503


def test_the_app_answers_problem_json_for_an_unknown_route() -> None:
    with TestClient(create_app(UNREACHABLE)) as client:
        response = client.get("/nowhere")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON


def test_the_engine_is_disposed_at_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[AsyncEngine] = []
    dispose = AsyncEngine.dispose

    async def spied(engine: AsyncEngine, close: bool = True) -> None:
        disposed.append(engine)
        await dispose(engine, close)

    monkeypatch.setattr(AsyncEngine, "dispose", spied)
    app = create_app(UNREACHABLE)
    with TestClient(app):
        assert disposed == []
        engine = app.state.engine

    assert disposed == [engine]
