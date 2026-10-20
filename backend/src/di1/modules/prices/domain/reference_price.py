"""Reference prices: the record, which source is preferred, and the date rule (spec §5; OQ-1,
OQ-3, OQ-7, OQ-14, OQ-25).

- A price is typed as a PU **or** a rate; the other value is calculated by Pricing.
- Any calendar date up to today (São Paulo, given by the caller).
- The typed quote, its decimals and bounds, and the maturity rules (OQ-1, OQ-3, OQ-14) are
  Pricing's one quote validation, which the service runs next to the date rule
  (``pricing.public.validate_quote``): domain code imports no other module.
- MANUAL is preferred over B3 for the same asset and date; only the exact date counts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from di1.shared.errors import ErrorDetail, future_date
from di1.shared.input_kind import InputKind


class PriceSource(StrEnum):
    """Where a reference observation came from (schema ``reference_prices_source_check``)."""

    MANUAL = "MANUAL"
    B3 = "B3"


SOURCE_PRIORITY: Final = (PriceSource.MANUAL, PriceSource.B3)
"""The preferred source first (spec §5)."""


@dataclass(frozen=True, slots=True)
class ReferencePriceRecord:
    """The reference price of one asset, date and source (schema ``prices.reference_prices``).

    There is one per (asset, date, source); a later set of the same key deletes the current row
    and inserts the new one, and a removal deletes it (OQ-25, OQ-26). Traceability is the current
    preferred price in this table (OQ-30), not ``id``.
    """

    id: UUID
    asset_id: UUID
    reference_date: date
    source: PriceSource
    input_kind: InputKind
    pu: Decimal
    rate: Decimal | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReferencePriceDay:
    """One date of an asset with at least one observation: the preferred one (MANUAL > B3)
    and the observation of each source, preferred first."""

    reference_date: date
    preferred: ReferencePriceRecord
    sources: tuple[ReferencePriceRecord, ...]


def validate_reference_date(reference_date: date, *, today: date) -> tuple[ErrorDetail, ...]:
    """A reference price is dated up to today in São Paulo (OQ-14); the maturity is Pricing's."""
    return (future_date("reference_date"),) if reference_date > today else ()


def choose_preferred(records: Iterable[ReferencePriceRecord]) -> ReferencePriceRecord | None:
    """The record of the most preferred source among those of one asset and date, or `None`
    when there is none: no other date is ever looked at (no carry-forward)."""
    by_source = {record.source: record for record in records}
    for source in SOURCE_PRIORITY:
        if source in by_source:
            return by_source[source]
    return None


def reference_days(records: Iterable[ReferencePriceRecord]) -> list[ReferencePriceDay]:
    """The records of one asset grouped by date, newest date first; each date has its preferred
    record and every source's record, preferred first."""
    by_date: dict[date, list[ReferencePriceRecord]] = {}
    for record in records:
        by_date.setdefault(record.reference_date, []).append(record)
    days = []
    for reference_date in sorted(by_date, reverse=True):
        sources = by_date[reference_date]
        preferred = sorted(sources, key=lambda r: SOURCE_PRIORITY.index(r.source))
        days.append(ReferencePriceDay(reference_date, preferred[0], tuple(preferred)))
    return days
