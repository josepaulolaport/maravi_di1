"""Phase 2 acceptance support: the real app (``create_app``) on a fresh PostgreSQL 16 database
migrated to head, with an injected clock (OQ-14; spec §15 D4), driven only through ``/api``.

The instrument type and asset class have no HTTP route (seeded catalogue roots); everything else
is created through the API, as a user would. Expected PUs are spec §4.1's formula evaluated here
with ``decimal`` (34 digits, half-up, stored at 10 places, OQ-3), never read from the code under
test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from pydantic import SecretStr

from di1.composition.consumers import processing_startup
from di1.main import create_app
from di1.platform.config import Settings
from di1.platform.database.engine import create_engine
from di1.platform.database.session import create_session_factory
from di1.platform.database.unit_of_work import unit_of_work_factory
from di1.platform.messaging.worker import WorkerResources
from di1.shared.clock import SAO_PAULO
from tests.fakes.clock import FixedClock
from tests.support.db import migrated_database_url, psycopg_url, seed_catalogue_roots

PROBLEM_JSON = "application/problem+json"


def expected_pu(rate: str, calendar_days: int) -> str:
    """Spec §4.1: ``PU = 100000 / (1 + taxa)^(dias_corridos/365)``, stored at 10 places."""
    with localcontext(prec=34, rounding=ROUND_HALF_UP):
        pu = Decimal(100000) / (1 + Decimal(rate)) ** (Decimal(calendar_days) / Decimal(365))
    return str(pu.quantize(Decimal("1E-10"), rounding=ROUND_HALF_UP))


def expected_rate(pu: str, calendar_days: int) -> str:
    """Spec §4.1: ``taxa = (100000 / PU)^(365/dias_corridos) − 1``, stored at 12 places."""
    with localcontext(prec=34, rounding=ROUND_HALF_UP):
        rate = (Decimal(100000) / Decimal(pu)) ** (Decimal(365) / Decimal(calendar_days)) - 1
    return str(rate.quantize(Decimal("1E-12"), rounding=ROUND_HALF_UP))


class TickingClock:
    """The API's clock: "today" is fixed (OQ-14), and each ``now`` is one second after the last,
    from noon of that day, so requests queued one after the other keep their order
    (``created_at``, the queue's FIFO key, OQ-46) as they would in real time."""

    def __init__(self, today: date) -> None:
        self._today = today
        self._ticks = 0

    def today(self) -> date:
        return self._today

    def now(self) -> datetime:
        self._ticks += 1
        return datetime.combine(self._today, time(12, 0), tzinfo=SAO_PAULO) + timedelta(
            seconds=self._ticks
        )


@contextmanager
def acceptance_app(today: date) -> Iterator[tuple[TestClient, str]]:
    """A client of the real app whose "today" is ``today``, and its database URL."""
    for url in migrated_database_url():
        seed_catalogue_roots(url)
        app = create_app(Settings(database_url=SecretStr(url)), clock=TickingClock(today))
        with TestClient(app) as client:
            yield client, url


def run_worker(database_url: str, now: datetime) -> None:
    """The processing worker starting at ``now``, in-process on the same database, with the real
    composition (``processing_startup``): it recovers, then sweeps every QUEUED request oldest
    first (OQ-45). The run messages left in the outbox are not relayed; RabbitMQ delivery is the
    worker's end-to-end test, not these."""
    asyncio.run(_run_worker(database_url, now))


async def _run_worker(database_url: str, now: datetime) -> None:
    engine = create_engine(Settings(database_url=SecretStr(database_url)))
    try:
        resources = WorkerResources(
            uow_factory=unit_of_work_factory(create_session_factory(engine)),
            clock=FixedClock(now.date(), fixed_now=now),
        )
        await processing_startup(resources)
    finally:
        await engine.dispose()


def date_statuses(database_url: str) -> dict[date, tuple[str | None, str | None]]:
    """``{date: (cash, portfolio)}`` from ``processing.date_status``, the only source of each
    date's processing status (OQ-23, OQ-31)."""
    rows = sql(
        database_url, "SELECT date, cash, portfolio FROM processing.date_status ORDER BY date"
    )
    return {row[0]: (row[1], row[2]) for row in rows}


def sql(database_url: str, statement: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Run one statement directly, for setup the API does not offer (a B3 price) and for proof
    that a write stored nothing else."""
    with psycopg.connect(psycopg_url(database_url), autocommit=True) as connection:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def create_di1_product(client: TestClient) -> str:
    response = client.post(
        "/api/products",
        json={
            "asset_class_id": 1,
            "code": "DI1",
            "name": "Futuro de Depósito Interfinanceiro",
            "futures": {
                "face_value": "100000",
                "contract_multiplier": "1",
                "settlement_method": "CASH",
            },
        },
    )
    assert response.status_code == 201, response.text
    product_id: str = response.json()["id"]
    return product_id


def create_instrument(client: TestClient, product_id: str, code: str, maturity: str) -> str:
    response = client.post(
        "/api/instruments",
        json={"product_id": product_id, "code": code, "maturity_date": maturity},
    )
    assert response.status_code == 201, response.text
    instrument_id: str = response.json()["id"]
    return instrument_id


def trade_body(
    asset_id: str,
    on: str,
    at: str,
    quantity: int,
    *,
    rate: str | None = None,
    pu: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "TRADE",
        "asset_id": asset_id,
        "date": on,
        "time": at,
        "signed_quantity": quantity,
    }
    if rate is not None:
        body |= {"input_kind": "RATE", "execution_rate": rate}
    if pu is not None:
        body |= {"input_kind": "PU", "execution_pu": pu}
    return body


def cash_body(on: str, at: str, amount: str) -> dict[str, Any]:
    return {"type": "CASH", "date": on, "time": at, "cash_amount": amount}


def price_body(
    asset_id: str, on: str, *, rate: str | None = None, pu: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"asset_id": asset_id, "reference_date": on}
    if rate is not None:
        body |= {"input_kind": "RATE", "rate": rate}
    if pu is not None:
        body |= {"input_kind": "PU", "pu": pu}
    return body


DERIVED_TABLES = (
    "processing.requests",
    "processing.date_status",
    "processing.issues",
    "platform.outbox_messages",
    "portfolio.positions",
    "portfolio.position_metrics",
    "portfolio.portfolio_metrics",
    "portfolio.cash_balances",
)
"""Everything a processing run, or a write that wrongly triggered one, would fill (OQ-31)."""


def derived_rows(database_url: str) -> dict[str, int]:
    """Row counts of `DERIVED_TABLES`: all zero when writes only saved their facts."""
    return {
        table: sql(database_url, f"SELECT count(*) FROM {table}")[0][0] for table in DERIVED_TABLES
    }


def problem(response: Any, status: int) -> list[tuple[str, str | None]]:
    """The ``(code, field)`` pairs of an RFC 9457 problem response (OQ-15)."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["status"] == status
    assert all(e["message"] for e in body["errors"])  # a pt-BR message for every error
    return [(e["code"], e["field"]) for e in body["errors"]]
