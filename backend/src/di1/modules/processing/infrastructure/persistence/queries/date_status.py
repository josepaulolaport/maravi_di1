"""SQL over ``processing.date_status`` (OQ-23, OQ-31, OQ-50 item 4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Insert, Select, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute

from di1.modules.processing.domain.date_status import Chain
from di1.modules.processing.infrastructure.persistence.models import DateStatusRow

CHAIN_COLUMN: dict[Chain, InstrumentedAttribute[str | None]] = {
    Chain.CASH: DateStatusRow.cash,
    Chain.POSITIONS: DateStatusRow.portfolio,
}
"""The one chain → column map: positions is the ``portfolio`` column."""


def date_range(start_date: date, end_date: date, *, for_update: bool) -> Select[DateStatusRow]:
    statement = (
        select(DateStatusRow)
        .where(DateStatusRow.day.between(start_date, end_date))
        .order_by(DateStatusRow.day)
    )
    return statement.with_for_update() if for_update else statement


def any_status_before(chain: Chain, day: date) -> Select[tuple[bool]]:
    return select(exists().where(DateStatusRow.day < day, CHAIN_COLUMN[chain].is_not(None)))


def upsert(day: date, values: dict[str, Any], now: datetime) -> Insert:
    """Inserts or replaces ``day``'s row; ``values`` are its status columns, by name."""
    statement = pg_insert(DateStatusRow).values(day=day, **values, updated_at=now)
    changed = {key: statement.excluded[key] for key in (*values, "updated_at")}
    return statement.on_conflict_do_update(index_elements=[DateStatusRow.day], set_=changed)
