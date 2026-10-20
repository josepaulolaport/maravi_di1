"""Statements over ``prices.reference_prices`` (OQ-25: one row per asset, date and source).

Replacing a price is one ``INSERT … ON CONFLICT (asset_id, reference_date, source) DO UPDATE``
that gives the row a new id and new timestamps: the same result as deleting the current row and
inserting the new one (OQ-26 item 7; OQ-50 item 7), but atomic, so two concurrent writes of the
same key both succeed and leave exactly one row (the later one) instead of failing the unique
constraint. Every statement returns whole `ReferencePriceRow`s.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.dml import ReturningDelete, ReturningInsert

from di1.modules.prices.infrastructure.persistence.models import ONE_PER_SOURCE, ReferencePriceRow


def replace_price(
    *,
    asset_id: UUID,
    reference_date: date,
    source: str,
    input_kind: str,
    pu: Decimal,
    rate: Decimal | None,
) -> ReturningInsert[ReferencePriceRow]:
    statement = insert(ReferencePriceRow).values(
        asset_id=asset_id,
        reference_date=reference_date,
        source=source,
        input_kind=input_kind,
        pu=pu,
        rate=rate,
    )
    return statement.on_conflict_do_update(
        constraint=ONE_PER_SOURCE,
        set_={
            "id": func.gen_random_uuid(),
            "input_kind": statement.excluded.input_kind,
            "pu": statement.excluded.pu,
            "rate": statement.excluded.rate,
            "created_at": func.now(),
            "updated_at": func.now(),
        },
    ).returning(ReferencePriceRow)


def delete_price(price_id: UUID) -> ReturningDelete[ReferencePriceRow]:
    return (
        delete(ReferencePriceRow)
        .where(ReferencePriceRow.id == price_id)
        .returning(ReferencePriceRow)
    )


def select_prices(
    asset_ids: Collection[UUID], dates: Collection[date]
) -> Select[ReferencePriceRow]:
    """Every observation of the given assets on exactly the given dates: one query for any
    number of assets and dates."""
    return select(ReferencePriceRow).where(
        ReferencePriceRow.asset_id.in_(list(asset_ids)),
        ReferencePriceRow.reference_date.in_(list(dates)),
    )


def select_prices_on_latest_date(asset_ids: Collection[UUID]) -> Select[ReferencePriceRow]:
    """Every observation of each asset on its latest date with one: at most one row per source,
    for any number of assets in one statement. Which source is preferred is the caller's rule."""
    latest = (
        select(
            ReferencePriceRow.asset_id,
            func.max(ReferencePriceRow.reference_date).label("reference_date"),
        )
        .where(ReferencePriceRow.asset_id.in_(list(asset_ids)))
        .group_by(ReferencePriceRow.asset_id)
        .subquery()
    )
    return select(ReferencePriceRow).join(
        latest,
        (ReferencePriceRow.asset_id == latest.c.asset_id)
        & (ReferencePriceRow.reference_date == latest.c.reference_date),
    )


def select_prices_in_range(
    asset_id: UUID, start_date: date, end_date: date
) -> Select[ReferencePriceRow]:
    return select(ReferencePriceRow).where(
        ReferencePriceRow.asset_id == asset_id,
        ReferencePriceRow.reference_date.between(start_date, end_date),
    )
