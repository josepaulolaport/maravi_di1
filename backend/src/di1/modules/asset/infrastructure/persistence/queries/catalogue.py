"""The SQL of the Asset repository. Codes compare on ``upper(code)``, the expression of the
schema's case-insensitive unique indexes, so the checks use them."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import InstrumentedAttribute

from di1.modules.asset.infrastructure.persistence.models import (
    AssetClassRow,
    FuturesRow,
    InstrumentRow,
    InstrumentTypeRow,
    ProductRow,
)

CODE_INDEXES = frozenset(
    {"instrument_types_code_uq", "asset_classes_code_uq", "products_code_uq", "instruments_code_uq"}
)
"""The unique indexes whose violation means "this code is taken"."""


def code_taken(column: InstrumentedAttribute[str], code: str) -> Select[bool]:
    return select(exists().where(func.upper(column) == func.upper(code)))


def instrument_types_with_classes() -> Select[InstrumentTypeRow, AssetClassRow]:
    """Every type, each joined to its classes (a type without classes appears once, with NULL:
    the outer join's class is typed non-null by SQLAlchemy but may be ``None``)."""
    return (
        select(InstrumentTypeRow, AssetClassRow)
        .outerjoin(AssetClassRow, AssetClassRow.instrument_type_id == InstrumentTypeRow.id)
        .order_by(InstrumentTypeRow.code, AssetClassRow.code)
    )


def asset_class_with_type(
    asset_class_id: int,
) -> Select[AssetClassRow, InstrumentTypeRow]:
    return (
        select(AssetClassRow, InstrumentTypeRow)
        .join(InstrumentTypeRow, InstrumentTypeRow.id == AssetClassRow.instrument_type_id)
        .where(AssetClassRow.id == asset_class_id)
    )


_instrument_count = (
    select(func.count())
    .where(InstrumentRow.product_id == ProductRow.id)
    .correlate(ProductRow)
    .scalar_subquery()
)


def products(
    *, instrument_type_code: str | None = None, product_id: UUID | None = None
) -> Select[ProductRow, AssetClassRow, InstrumentTypeRow, FuturesRow, int]:
    """Products with their class, type, futures row (if any) and instrument count, by code."""
    statement = (
        select(ProductRow, AssetClassRow, InstrumentTypeRow, FuturesRow, _instrument_count)
        .join(AssetClassRow, AssetClassRow.id == ProductRow.asset_class_id)
        .join(InstrumentTypeRow, InstrumentTypeRow.id == AssetClassRow.instrument_type_id)
        .outerjoin(FuturesRow, FuturesRow.product_id == ProductRow.id)
        .order_by(ProductRow.code, ProductRow.id)
    )
    if instrument_type_code is not None:
        statement = statement.where(
            func.upper(InstrumentTypeRow.code) == func.upper(instrument_type_code)
        )
    if product_id is not None:
        statement = statement.where(ProductRow.id == product_id)
    return statement


def instruments(
    *,
    product_id: UUID | None = None,
    instrument_id: UUID | None = None,
    instrument_ids: Collection[UUID] | None = None,
) -> Select[InstrumentRow, ProductRow, AssetClassRow, InstrumentTypeRow, FuturesRow]:
    """Instruments with product, class, type and futures, by maturity (undated last), then code."""
    statement = (
        select(InstrumentRow, ProductRow, AssetClassRow, InstrumentTypeRow, FuturesRow)
        .join(ProductRow, ProductRow.id == InstrumentRow.product_id)
        .join(AssetClassRow, AssetClassRow.id == ProductRow.asset_class_id)
        .join(InstrumentTypeRow, InstrumentTypeRow.id == AssetClassRow.instrument_type_id)
        .outerjoin(FuturesRow, FuturesRow.product_id == ProductRow.id)
        .order_by(
            InstrumentRow.maturity_date.asc().nulls_last(), InstrumentRow.code, InstrumentRow.id
        )
    )
    if product_id is not None:
        statement = statement.where(InstrumentRow.product_id == product_id)
    if instrument_id is not None:
        statement = statement.where(InstrumentRow.id == instrument_id)
    if instrument_ids is not None:
        statement = statement.where(InstrumentRow.id.in_(list(instrument_ids)))
    return statement
