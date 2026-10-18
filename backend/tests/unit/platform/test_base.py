"""The shared ORM base maps Python types to the schema's PostgreSQL types.

CLAUDE.md §2 and schema.md decision 6: money, PU and rates are `Decimal` stored as unbounded
`NUMERIC`, never float. schema.sql: every timestamp is `TIMESTAMPTZ`, every id `UUID`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base


class _Sample(Base):
    __tablename__ = "sample"
    __table_args__ = {"schema": "platform_test"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    amount: Mapped[Decimal]
    created_at: Mapped[datetime]


def _column_type(name: str) -> object:
    return _Sample.__table__.c[name].type


def test_decimal_maps_to_unbounded_numeric_returning_decimal() -> None:
    column_type = _column_type("amount")

    assert isinstance(column_type, Numeric)
    assert (column_type.precision, column_type.scale) == (None, None)
    assert column_type.asdecimal is True


def test_datetime_maps_to_timestamptz() -> None:
    column_type = _column_type("created_at")

    assert isinstance(column_type, DateTime)
    assert column_type.timezone is True


def test_uuid_maps_to_native_uuid() -> None:
    column_type = _column_type("id")

    assert isinstance(column_type, Uuid)
    assert column_type.as_uuid is True
