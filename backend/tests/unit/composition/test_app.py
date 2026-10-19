"""The application factory (X3): problem+json everywhere, a health check that fails safely and
quickly, and the engine disposed at shutdown.

No database is needed: the engine connects lazily, so an unreachable or silent server only matters
to ``/health``, which must answer 503 problem+json without leaking the error.
"""

from __future__ import annotations

import asyncio
import logging
import socket
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


def test_a_silent_server_answers_503(silent_server: int) -> None:
    hung = Settings(
        database_url=SecretStr(f"postgresql+psycopg://di1:x@127.0.0.1:{silent_server}/di1")
    )
    with TestClient(create_app(hung, health_timeout=0.5)) as client:
        response = client.get("/health")

    assert response.status_code == 503


class _SlowConnection:
    """A connection whose ``SELECT 1`` answers only after ``delay`` seconds."""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def __aenter__(self) -> _SlowConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _: object) -> None:
        await asyncio.sleep(self._delay)


class _SlowEngine:
    def __init__(self, delay: float) -> None:
        self._delay = delay

    def connect(self) -> _SlowConnection:
        return _SlowConnection(self._delay)


@pytest.mark.parametrize(("delay", "status"), [(0.0, 200), (30.0, 503)])
def test_the_health_timeout_bounds_the_probe(delay: float, status: int) -> None:
    app = create_app(UNREACHABLE, health_timeout=0.05)
    with TestClient(app) as client:
        app.state.engine, real = _SlowEngine(delay), app.state.engine
        response = client.get("/health")
        app.state.engine = real

    assert response.status_code == status


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
