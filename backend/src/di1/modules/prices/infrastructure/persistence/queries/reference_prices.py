"""Statements over ``prices.reference_prices`` (OQ-25: one row per asset, date and source).

Replacing a price is one ``INSERT … ON CONFLICT (asset_id, reference_date, source) DO UPDATE``
that gives the row a new id and new timestamps: the same result as deleting the current row and
inserting the new one (OQ-26 item 7), but atomic, so two concurrent writes of the same key both
succeed and leave exactly one row (the later one) instead of failing the unique constraint.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Executable, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from di1.modules.prices.infrastructure.persistence.models import ReferencePriceModel

_COLUMNS = (
    ReferencePriceModel.id,
    ReferencePriceModel.asset_id,
    ReferencePriceModel.reference_date,
    ReferencePriceModel.source,
    ReferencePriceModel.input_kind,
    ReferencePriceModel.pu,
    ReferencePriceModel.rate,
    ReferencePriceModel.created_at,
    ReferencePriceModel.updated_at,
)


def replace_price(
    *,
    asset_id: UUID,
    reference_date: date,
    source: str,
    input_kind: str,
    pu: Decimal,
    rate: Decimal | None,
) -> Executable:
    statement = insert(ReferencePriceModel).values(
        asset_id=asset_id,
        reference_date=reference_date,
        source=source,
        input_kind=input_kind,
        pu=pu,
        rate=rate,
    )
    return statement.on_conflict_do_update(
        constraint="reference_prices_one_per_source",
        set_={
            "id": func.gen_random_uuid(),
            "input_kind": statement.excluded.input_kind,
            "pu": statement.excluded.pu,
            "rate": statement.excluded.rate,
            "calculation_method": statement.excluded.calculation_method,
            "created_at": func.now(),
            "updated_at": func.now(),
        },
    ).returning(*_COLUMNS)


def select_price(price_id: UUID) -> Executable:
    return select(*_COLUMNS).where(ReferencePriceModel.id == price_id)


def delete_price(price_id: UUID) -> Executable:
    return (
        delete(ReferencePriceModel).where(ReferencePriceModel.id == price_id).returning(*_COLUMNS)
    )


def select_prices(asset_ids: Collection[UUID], dates: Collection[date]) -> Executable:
    """Every observation of the given assets on exactly the given dates: one query for any
    number of assets and dates."""
    return select(*_COLUMNS).where(
        ReferencePriceModel.asset_id.in_(list(asset_ids)),
        ReferencePriceModel.reference_date.in_(list(dates)),
    )


def select_prices_on_latest_date(asset_ids: Collection[UUID]) -> Executable:
    """Every observation of each asset on its latest date with one: at most one row per source,
    for any number of assets in one statement. Which source is preferred is the caller's rule."""
    latest = (
        select(
            ReferencePriceModel.asset_id,
            func.max(ReferencePriceModel.reference_date).label("reference_date"),
        )
        .where(ReferencePriceModel.asset_id.in_(list(asset_ids)))
        .group_by(ReferencePriceModel.asset_id)
        .subquery()
    )
    return select(*_COLUMNS).join(
        latest,
        (ReferencePriceModel.asset_id == latest.c.asset_id)
        & (ReferencePriceModel.reference_date == latest.c.reference_date),
    )


def select_prices_in_range(asset_id: UUID, start_date: date, end_date: date) -> Executable:
    return select(*_COLUMNS).where(
        ReferencePriceModel.asset_id == asset_id,
        ReferencePriceModel.reference_date.between(start_date, end_date),
    )
