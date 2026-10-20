"""SQL over ``processing.issues``: a date's Pendências are replaced whenever it is processed
(OQ-26 item 5)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Delete, Insert, Select, delete, insert, select

from di1.modules.processing.infrastructure.persistence.models import IssueRow


def current() -> Select[IssueRow]:
    """Every stored issue, newest affected date first."""
    return select(IssueRow).order_by(
        IssueRow.affected_date.desc(), IssueRow.issue_type, IssueRow.id
    )


def delete_of_date(day: date) -> Delete:
    return delete(IssueRow).where(IssueRow.affected_date == day)


def insert_issues(rows: Sequence[dict[str, Any]]) -> Insert:
    return insert(IssueRow).values(list(rows))
