"""The application against a real PostgreSQL 16 (X3): ``/health`` answers 200, and a request's Unit
of Work reaches the database through the app's session factory, commits only when told to and
returns its connection."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from di1.composition.dependencies import get_unit_of_work
from di1.main import create_app
from di1.platform.config import Settings
from di1.platform.database.unit_of_work import UnitOfWork
from tests.integration.databases import fresh_database_url

Uow = Annotated[UnitOfWork, Depends(get_unit_of_work)]


@pytest.fixture
def settings() -> Iterator[Settings]:
    for url in fresh_database_url():
        yield Settings(database_url=SecretStr(url))


def test_health_is_ok_when_the_database_answers(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_a_request_unit_of_work_commits_only_when_told_to(settings: Settings) -> None:
    app = create_app(settings)

    @app.post("/setup")
    async def setup(uow: Uow) -> None:
        await uow.session.execute(text("CREATE TABLE probe (value integer)"))
        await uow.commit()

    @app.post("/write/{value}")
    async def write(value: int, commit: bool, uow: Uow) -> None:
        await uow.session.execute(text("INSERT INTO probe VALUES (:v)"), {"v": value})
        if commit:
            await uow.commit()

    @app.get("/values")
    async def values(uow: Uow) -> list[int]:
        return list((await uow.session.execute(text("SELECT value FROM probe"))).scalars())

    with TestClient(app) as client:
        client.post("/setup")
        client.post("/write/1", params={"commit": False})
        client.post("/write/2", params={"commit": True})
        stored = client.get("/values").json()
        checked_out = app.state.engine.pool.checkedout()

    assert stored == [2]
    assert checked_out == 0
