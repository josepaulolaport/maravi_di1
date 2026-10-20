"""Pendências (spec §10.3; OQ-19, OQ-31, OQ-37): what a processed date still needs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class IssueType(StrEnum):
    """The two Pendências (OQ-31)."""

    MISSING_REFERENCE_PRICE = "MISSING_REFERENCE_PRICE"
    EXPIRED_OPEN_POSITION = "EXPIRED_OPEN_POSITION"


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """One Pendência. ``id`` and ``request_id`` are set once it is stored."""

    issue_type: IssueType
    asset_id: UUID | None
    affected_date: date
    required_price_date: date | None
    id: UUID | None = None
    request_id: UUID | None = None


def deduplicate(issues: Sequence[IssueRecord]) -> list[IssueRecord]:
    """One issue per obligation (OQ-37): a missing price per (asset, needed date), an expired open
    position per asset. Each keeps its earliest affected date; the result is newest affected date
    first."""
    kept: dict[tuple[IssueType, UUID | None, date | None], IssueRecord] = {}
    for issue in sorted(issues, key=lambda i: i.affected_date):
        needed = (
            issue.required_price_date
            if issue.issue_type is IssueType.MISSING_REFERENCE_PRICE
            else None
        )
        kept.setdefault((issue.issue_type, issue.asset_id, needed), issue)
    return sorted(kept.values(), key=lambda i: i.affected_date, reverse=True)
