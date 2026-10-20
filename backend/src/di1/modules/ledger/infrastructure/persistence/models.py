"""ORM mapping of ``ledger.entries``, mirroring docs/schema.sql (OQ-24). The migrations own the
table, its CHECKs and its indexes; nothing is generated from this mapping."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import BigInteger, Identity, Integer, Numeric, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base


class LedgerEntryRow(Base):
    __tablename__ = "entries"
    __table_args__ = {"schema": "ledger"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(String(8))
    entry_date: Mapped[date]
    entry_time: Mapped[time] = mapped_column(Time(timezone=False))
    seq: Mapped[int] = mapped_column(BigInteger, Identity())
    asset_id: Mapped[uuid.UUID | None]
    signed_quantity: Mapped[int | None] = mapped_column(Integer)
    execution_pu: Mapped[Decimal | None]
    execution_rate: Mapped[Decimal | None]
    input_kind: Mapped[str | None] = mapped_column(String(8))
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2, asdecimal=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
