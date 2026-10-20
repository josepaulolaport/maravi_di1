"""ORM mapping of ``ledger.entries``, mirroring docs/schema.sql (OQ-24). The migrations own the
table, its CHECKs and its indexes; nothing is generated from this mapping.

Entries are deleted for good (user decision 2026-10-19), so ``deleted_at`` and
``deletion_batch_id`` are not mapped; the integrator's migration drops them from the table."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import BigInteger, Identity, Integer, Numeric, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base


class LedgerEntryRow(Base):
    __tablename__ = "entries"
    __table_args__ = {"schema": "ledger"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    type: Mapped[str] = mapped_column(String(8))
    entry_date: Mapped[date]
    entry_time: Mapped[time] = mapped_column(Time(timezone=False))
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    asset_id: Mapped[uuid.UUID | None]
    signed_quantity: Mapped[int | None] = mapped_column(Integer)
    execution_pu: Mapped[Decimal | None]
    execution_rate: Mapped[Decimal | None]
    input_kind: Mapped[str | None] = mapped_column(String(8))
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2, asdecimal=True))
    description: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
