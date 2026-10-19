"""ORM models of the ``asset`` schema, mirroring docs/schema.sql (the migrations own the DDL).

The case-insensitive unique indexes on ``upper(code)`` and the CHECKs live only in the database;
nothing is created from this metadata.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from di1.platform.database.base import Base

SCHEMA = "asset"


class InstrumentTypeRow(Base):
    __tablename__ = "instrument_types"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))


class AssetClassRow(Base):
    __tablename__ = "asset_classes"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    instrument_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(f"{SCHEMA}.instrument_types.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(150))


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_class_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(f"{SCHEMA}.asset_classes.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FuturesRow(Base):
    __tablename__ = "futures"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.products.id", ondelete="RESTRICT"), primary_key=True
    )
    face_value: Mapped[Decimal]
    contract_multiplier: Mapped[Decimal] = mapped_column(server_default=text("1"))
    settlement_method: Mapped[str] = mapped_column(String(32))
    settlement_description: Mapped[str | None] = mapped_column(Text)


class InstrumentRow(Base):
    __tablename__ = "instruments"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.products.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(128))
    maturity_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
