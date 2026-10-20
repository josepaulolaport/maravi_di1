"""Seeding and reading ``processing.*`` (and an instrument for issues) with plain SQL."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from di1.modules.processing.application.interfaces.repositories import ChainHistory
from di1.modules.processing.application.services.processing import ProcessingService
from di1.modules.processing.infrastructure.messaging.outbox_run_messages import (
    OutboxRunMessages,
)
from di1.modules.processing.infrastructure.persistence.repositories import (
    SqlDateStatusRepository,
    SqlIssueRepository,
    SqlRequestRepository,
)
from di1.shared.clock import Clock
from tests.unit.processing.fakes import FakeAssets, FakeChainHistory, SteppingClock


def make_service(
    *,
    assets: FakeAssets | None = None,
    history: ChainHistory | None = None,
    requests: SqlRequestRepository | None = None,
    clock: Clock | None = None,
) -> ProcessingService:
    return ProcessingService(
        requests=requests or SqlRequestRepository(),
        date_statuses=SqlDateStatusRepository(),
        issues=SqlIssueRepository(),
        chain_history=history or FakeChainHistory(),
        assets=assets or FakeAssets(),
        clock=clock or SteppingClock(),
        run_messages=OutboxRunMessages(),
    )


async def seed_statuses(
    engine: AsyncEngine,
    rows: Mapping[date, tuple[str | None, str | None]],
    processed_at: datetime | None = None,
) -> None:
    """``{date: (portfolio, cash)}``; each chain with a status was processed at
    ``processed_at``."""
    async with engine.begin() as connection:
        for day, (portfolio, cash) in rows.items():
            await connection.execute(
                text(
                    "INSERT INTO processing.date_status (date, portfolio, cash,"
                    " portfolio_processed_at, cash_processed_at) VALUES (:d, :p, :c, :pa, :ca)"
                ),
                {
                    "d": day,
                    "p": portfolio,
                    "c": cash,
                    "pa": processed_at if portfolio is not None else None,
                    "ca": processed_at if cash is not None else None,
                },
            )


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        value = await connection.scalar(text(f"SELECT count(*) FROM {table}"))
        return int(value or 0)


async def request_statuses(engine: AsyncEngine) -> dict[uuid.UUID, str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT id, status FROM processing.requests"))
        return {row[0]: row[1] for row in result}


async def seed_instrument(engine: AsyncEngine, code: str) -> uuid.UUID:
    async with engine.begin() as connection:
        type_id = await connection.scalar(
            text(
                "INSERT INTO asset.instrument_types (code, name) VALUES ('FUTURE', 'Futuro')"
                " RETURNING id"
            )
        )
        class_id = await connection.scalar(
            text(
                "INSERT INTO asset.asset_classes (instrument_type_id, code, name)"
                " VALUES (:t, 'INTEREST_RATE_FUTURE', 'Juros') RETURNING id"
            ),
            {"t": type_id},
        )
        product_id = await connection.scalar(
            text(
                "INSERT INTO asset.products (asset_class_id, code, name)"
                " VALUES (:c, 'DI1', 'DI1') RETURNING id"
            ),
            {"c": class_id},
        )
        instrument_id = await connection.scalar(
            text(
                "INSERT INTO asset.instruments (product_id, code, maturity_date)"
                " VALUES (:p, :code, '2029-01-02') RETURNING id"
            ),
            {"p": product_id, "code": code},
        )
    assert isinstance(instrument_id, uuid.UUID)
    return instrument_id
