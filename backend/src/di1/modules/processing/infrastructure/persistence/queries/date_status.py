"""SQL over ``processing.date_status`` (OQ-23, OQ-31)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, select

from di1.modules.processing.infrastructure.persistence.models import DateStatusModel


def select_range(start_date: date, end_date: date) -> Select[*tuple[Any, ...]]:
    return (
        select(
            DateStatusModel.day,
            DateStatusModel.portfolio,
            DateStatusModel.cash,
            DateStatusModel.portfolio_processed_at,
            DateStatusModel.cash_processed_at,
        )
        .where(DateStatusModel.day.between(start_date, end_date))
        .order_by(DateStatusModel.day)
    )
