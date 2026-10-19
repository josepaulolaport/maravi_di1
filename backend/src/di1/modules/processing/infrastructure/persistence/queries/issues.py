"""SQL over ``processing.issues``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select

from di1.modules.processing.infrastructure.persistence.models import IssueModel


def select_current() -> Select[*tuple[Any, ...]]:
    """Every stored issue, newest affected date first; current because the run replaces a
    date's issues when it publishes the date (OQ-26 item 5)."""
    return select(
        IssueModel.id,
        IssueModel.request_id,
        IssueModel.issue_type,
        IssueModel.asset_id,
        IssueModel.affected_date,
        IssueModel.required_price_date,
    ).order_by(IssueModel.affected_date.desc(), IssueModel.issue_type, IssueModel.id)
