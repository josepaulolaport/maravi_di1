"""Reference-price rules (spec §5; OQ-1, OQ-3, OQ-7, OQ-14, OQ-25).

- A price is typed as a PU **or** a rate; the other value is calculated by Pricing.
- Any calendar date up to today (São Paulo, given by the caller).
- The typed quote, its decimals and bounds, and the maturity rules (OQ-1, OQ-3, OQ-14) are
  Pricing's one quote validation, which the caller passes in as a `QuoteRule`
  (``pricing.public.QuoteValidator``): domain code imports no other module.
- MANUAL is preferred over B3 for the same asset and date; only the exact date counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Protocol

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

SOURCE_PRIORITY: Final = ("MANUAL", "B3")
"""The preferred source first (spec §5). Values of `prices.public.PriceSource`."""


class QuoteRule(Protocol):
    """The validation of a typed quote: the typed value, or ``None``, and every problem found
    (``pricing.public.QuoteValidator``, whose field names this module's requests use)."""

    def __call__(
        self,
        kind: InputKind,
        *,
        pu: Decimal | None,
        rate: Decimal | None,
        reference_date: date,
        maturity_date: date | None,
    ) -> tuple[Decimal | None, Sequence[ErrorDetail]]: ...


@dataclass(frozen=True, slots=True)
class TypedQuote:
    """The value the user typed, the single authoritative input."""

    kind: InputKind
    value: Decimal


def validate_reference_price(
    *,
    today: date,
    maturity_date: date | None,
    reference_date: date,
    input_kind: InputKind,
    pu: Decimal | None,
    rate: Decimal | None,
    validate_quote: QuoteRule,
) -> TypedQuote:
    """The typed quote of a reference price, or `DomainError` with every problem found."""
    errors: list[ErrorDetail] = []
    if reference_date > today:
        errors.append(
            ErrorDetail(
                ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "reference_date"
            )
        )
    value, quote_errors = validate_quote(
        input_kind, pu=pu, rate=rate, reference_date=reference_date, maturity_date=maturity_date
    )
    errors.extend(quote_errors)
    if errors:
        raise DomainError(*errors)
    assert value is not None  # the quote rule reported a missing value
    return TypedQuote(input_kind, value)


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
