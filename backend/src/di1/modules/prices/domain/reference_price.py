"""Reference-price rules (spec §5; OQ-1, OQ-3, OQ-7, OQ-14, OQ-25).

- A price is typed as a PU **or** a rate; the other value is calculated by Pricing.
- Any calendar date up to today (São Paulo, given by the caller) and up to the maturity date
  inclusive. On the maturity date the PU is typed and the rate is 0, so a typed rate is refused.
- A typed PU has at most 10 places and a typed rate at most 12; more is rejected, never rounded.
- The value bounds are only the schema's: PU > 0, rate > −1.
- MANUAL is preferred over B3 for the same asset and date; only the exact date counts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Protocol

from di1.shared.decimals import PU_PLACES, RATE_PLACES, fits_places
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind

SOURCE_PRIORITY: Final = ("MANUAL", "B3")
"""The preferred source first (spec §5). Values of `prices.public.PriceSource`."""


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
) -> TypedQuote:
    """The typed quote of a reference price, or `DomainError` with every problem found."""
    errors = [*_date_errors(today, maturity_date, reference_date)]
    if input_kind is InputKind.PU:
        errors += _typed_errors(pu, rate, typed="pu", other="rate")
        value = pu
    else:
        errors += _typed_errors(rate, pu, typed="rate", other="pu")
        if maturity_date is not None and reference_date == maturity_date:
            errors.append(_invalid("Na data de vencimento informe o PU.", "rate"))
        value = rate
    if errors:
        raise DomainError(*errors)
    assert value is not None  # _typed_errors reported a missing value
    return TypedQuote(input_kind, value)


def _date_errors(
    today: date, maturity_date: date | None, reference_date: date
) -> list[ErrorDetail]:
    errors = []
    if reference_date > today:
        errors.append(
            ErrorDetail(
                ErrorCode.FUTURE_DATE, "A data não pode ser posterior a hoje.", "reference_date"
            )
        )
    if maturity_date is not None and reference_date > maturity_date:
        errors.append(
            ErrorDetail(
                ErrorCode.CONTRACT_MATURED, "O contrato já venceu nesta data.", "reference_date"
            )
        )
    return errors


_MISSING: Final = {"pu": "Informe o PU.", "rate": "Informe a taxa."}
_ONLY: Final = {
    "pu": "Informe apenas o PU, sem a taxa.",
    "rate": "Informe apenas a taxa, sem o PU.",
}
_PLACES: Final = {"pu": PU_PLACES, "rate": RATE_PLACES}


def _typed_errors(
    value: Decimal | None, other_value: Decimal | None, *, typed: str, other: str
) -> list[ErrorDetail]:
    errors = []
    if other_value is not None:
        errors.append(_invalid(_ONLY[typed], other))
    if value is None:
        errors.append(_invalid(_MISSING[typed], typed))
    elif not value.is_finite():
        errors.append(_invalid("Informe um número válido.", typed))
    elif not fits_places(value, _PLACES[typed]):
        errors.append(_invalid(f"Use no máximo {_PLACES[typed]} casas decimais.", typed))
    elif typed == "pu" and value <= 0:
        errors.append(_invalid("O valor deve ser maior que zero.", typed))
    elif typed == "rate" and value <= -1:
        errors.append(_invalid("A taxa deve ser maior que −100%.", typed))
    return errors


def _invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


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
