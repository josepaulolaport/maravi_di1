"""ORM mirror of ``prices.reference_prices`` (docs/schema.sql; OQ-25). The migrations own the DDL,
its CHECKs, unique constraint and index; nothing is generated from this model.
``calculation_method`` stays in the table, unused, and is not mapped."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base

ONE_PER_SOURCE = "reference_prices_one_per_source"
"""The unique constraint on (asset_id, reference_date, source) that a replace conflicts on."""


class ReferencePriceRow(Base):
    __tablename__ = "reference_prices"
    __table_args__ = {"schema": "prices"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.instruments.id", ondelete="RESTRICT")
    )
    reference_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    input_kind: Mapped[str] = mapped_column(String(8))
    pu: Mapped[Decimal]
    rate: Mapped[Decimal | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
