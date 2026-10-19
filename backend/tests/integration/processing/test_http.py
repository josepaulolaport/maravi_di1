"""Processing's routes over PostgreSQL 16, through the factories the composition will use
(``dependencies.py``, ``create_router``) and a request-scoped Unit of Work."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.composition.errors import install_problem_handlers
from di1.modules.ledger.public import CashMovementRecord, TradeRecord
from di1.modules.processing.dependencies import make_processing_service
from di1.modules.processing.presentation.http.router import create_router
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from tests.unit.processing.fakes import FakeAssets, SteppingClock

BODY = {"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "ALL"}


class _NoEntries:
    """A `LedgerReader` with an empty ledger: every chain is in its zero state."""

    async def get_trades(self, start_date: date, end_date: date) -> list[TradeRecord]:
        return []

    async def get_cash_movements(
        self, start_date: date, end_date: date
    ) -> list[CashMovementRecord]:
        return []


@pytest.fixture
def client(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[TestClient]:
    service = make_processing_service(
        assets=FakeAssets(),
        ledger=_NoEntries(),
        clock=SteppingClock(),
    )

    async def unit_of_work() -> AsyncIterator[UnitOfWork]:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(create_router(lambda: service, unit_of_work))
    with TestClient(app) as client:
        yield client


def test_gate_2_requests_can_be_queued_listed_and_cancelled(
    client: TestClient,
) -> None:
    first = client.post("/processing/requests", json=BODY)
    second = client.post("/processing/requests", json=BODY)
    assert (first.status_code, second.status_code) == (201, 201)

    listed = client.get("/processing/requests").json()
    assert [r["id"] for r in listed["items"]] == [second.json()["id"], first.json()["id"]]
    assert listed["next_cursor"] is None

    cancelled = client.post(f"/processing/requests/{first.json()['id']}/cancel")
    assert (cancelled.status_code, cancelled.json()["status"]) == (200, "CANCELLED")

    again = client.post(f"/processing/requests/{first.json()['id']}/cancel")
    assert again.status_code == 409
    assert again.headers["content-type"] == "application/problem+json"


def test_the_preview_and_the_issues_answer_from_the_database(client: TestClient) -> None:
    preview = client.get(
        "/processing/preview",
        params={"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "ALL"},
    )
    issues = client.get("/processing/issues")

    assert preview.json()["predecessor"] == {"cash": "ZERO_STATE", "positions": "ZERO_STATE"}
    assert issues.json() == {"items": []}
