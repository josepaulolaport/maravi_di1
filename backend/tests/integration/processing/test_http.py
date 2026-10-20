"""Processing's routes over PostgreSQL 16, through the factories the composition will use
(``dependencies.py``, ``create_router``) and a request-scoped Unit of Work."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from di1.modules.ledger.public import EntryType, LedgerEntry
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.dependencies import build_processing_service
from di1.modules.processing.presentation.http.router import create_router
from di1.platform.database.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWork
from tests.support.fakes import FakeAssetReader, stepping_clock
from tests.support.http import app_client

BODY = {"start_date": "2026-10-14", "end_date": "2026-10-16", "scope": "ALL"}


class _NoEntries:
    """A `LedgerReader` with an empty ledger: every chain is in its zero state."""

    async def get_trades(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return []

    async def get_cash_movements(self, start_date: date, end_date: date) -> list[LedgerEntry]:
        return []

    async def has_entries_on_or_before(
        self, day: date, *, entry_type: EntryType | None = None
    ) -> bool:
        return False


@pytest.fixture
def client(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[TestClient]:
    clock = stepping_clock()

    async def unit_of_work() -> AsyncIterator[UnitOfWork]:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    UOW = Depends(unit_of_work)  # noqa: N806 (a dependency object, as the routers build them)

    def service(uow: UnitOfWork = UOW) -> ProcessingService:
        return build_processing_service(
            uow, assets=FakeAssetReader(), ledger=_NoEntries(), clock=clock
        )

    with app_client(create_router(get_service=service)) as client:
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
