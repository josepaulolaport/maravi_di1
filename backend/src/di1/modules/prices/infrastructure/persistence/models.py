"""ORM mirror of ``prices.reference_prices`` (docs/schema.sql; OQ-25). The migrations own the
DDL; nothing is generated from this model."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base


class ReferencePriceModel(Base):
    __tablename__ = "reference_prices"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL','B3')", name="reference_prices_source_check"),
        CheckConstraint("input_kind IN ('PU','RATE')", name="reference_prices_input_kind_check"),
        CheckConstraint("pu > 0", name="reference_prices_pu_positive"),
        CheckConstraint("rate IS NULL OR rate > -1", name="reference_prices_rate_valid"),
        CheckConstraint(
            "input_kind <> 'RATE' OR rate IS NOT NULL",
            name="reference_prices_rate_present_if_entered",
        ),
        UniqueConstraint(
            "asset_id", "reference_date", "source", name="reference_prices_one_per_source"
        ),
        Index("reference_prices_date_idx", "reference_date", "asset_id"),
        {"schema": "prices"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.instruments.id", ondelete="RESTRICT")
    )
    reference_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    input_kind: Mapped[str] = mapped_column(String(8))
    pu: Mapped[Decimal]
    rate: Mapped[Decimal | None]
    calculation_method: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
