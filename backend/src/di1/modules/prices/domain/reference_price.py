"""Reference-price rules (spec §5; OQ-1, OQ-3, OQ-7, OQ-14, OQ-25).

- A price is typed as a PU **or** a rate; the other value is calculated by Pricing.
- Any calendar date up to today (São Paulo, given by the caller).
- The typed quote, its decimals and bounds, and the maturity rules (OQ-1, OQ-3, OQ-14) are
  Pricing's one quote validation, which the service runs next to the date rule
  (``pricing.public.validate_quote``): domain code imports no other module.
- MANUAL is preferred over B3 for the same asset and date; only the exact date counts.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Final, Protocol

from di1.shared.errors import ErrorDetail, future_date

SOURCE_PRIORITY: Final = ("MANUAL", "B3")
"""The preferred source first (spec §5). Values of `prices.public.PriceSource`."""


def validate_reference_date(reference_date: date, *, today: date) -> tuple[ErrorDetail, ...]:
    """A reference price is dated up to today in São Paulo (OQ-14); the maturity is Pricing's."""
    return (future_date("reference_date"),) if reference_date > today else ()


class SourcedObservation(Protocol):
    @property
    def source(self) -> str: ...


def choose_preferred[T: SourcedObservation](observations: Iterable[T]) -> T | None:
    """The observation of the most preferred source among those of one asset and date, or
    `None` when there is none: no other date is ever looked at (no carry-forward)."""
    by_source = {observation.source: observation for observation in observations}
    for source in SOURCE_PRIORITY:
        if source in by_source:
            return by_source[source]
    return None
