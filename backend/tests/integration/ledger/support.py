"""Seed data and helpers for Ledger's PostgreSQL tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from di1.modules.ledger.domain.entries import EntryDraft, EntryType
from di1.shared.input_kind import InputKind
from tests.unit.ledger.fakes import DI1F27, DI1F28, DI1F29, DI1V26, PRODUCT_ID

TODAY = date(2026, 10, 18)


async def seed_contracts(connection: AsyncConnection) -> None:
    """The fixtures' DI1 product and contracts, with the ids `FakeAssets` knows."""
    await connection.execute(
        text("INSERT INTO asset.instrument_types (id, code, name) VALUES (1, 'FUTURE', 'Futuros');")
    )
    await connection.execute(
        text(
            "INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)"
            " VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros')"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO asset.products (id, asset_class_id, code, name)"
            " VALUES (:id, 1, 'DI1', 'Futuro DI1')"
        ),
        {"id": PRODUCT_ID},
    )
    await connection.execute(
        text(
            "INSERT INTO asset.futures (product_id, face_value, settlement_method)"
            " VALUES (:id, 100000, 'CASH')"
        ),
        {"id": PRODUCT_ID},
    )
    for contract in (DI1F27, DI1F28, DI1F29, DI1V26):
        await connection.execute(
            text(
                "INSERT INTO asset.instruments (id, product_id, code, maturity_date)"
                " VALUES (:id, :product_id, :code, :maturity)"
            ),
            {
                "id": contract.id,
                "product_id": PRODUCT_ID,
                "code": contract.code,
                "maturity": contract.maturity_date,
            },
        )


def trade(
    entry_date: date = date(2026, 10, 14),
    entry_time: time = time(14, 10),
    *,
    quantity: int = 10,
    rate: str = "0.10",
    contract_id: Any = DI1F28.id,
) -> EntryDraft:
    return EntryDraft(
        type=EntryType.TRADE,
        entry_date=entry_date,
        entry_time=entry_time,
        asset_id=contract_id,
        signed_quantity=quantity,
        input_kind=InputKind.RATE,
        execution_rate=Decimal(rate),
    )


def cash(
    entry_date: date = date(2026, 10, 14),
    entry_time: time = time(9, 0),
    *,
    amount: str = "1500000.00",
    description: str | None = None,
) -> EntryDraft:
    return EntryDraft(
        type=EntryType.CASH,
        entry_date=entry_date,
        entry_time=entry_time,
        cash_amount=Decimal(amount),
        description=description,
    )


async def fetch(
    session_factory: async_sessionmaker[AsyncSession], sql: str, **params: Any
) -> Sequence[Row[Any]]:
    async with session_factory() as session:
        return (await session.execute(text(sql), params)).all()
