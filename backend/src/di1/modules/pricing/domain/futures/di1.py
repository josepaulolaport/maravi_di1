"""DI1 pricing: PU ↔ rate, DC/365 with calendar days (spec §4.1; interfaces "Pricing").

    PU   = face_value / (1 + taxa)^(dias_corridos / 365)
    taxa = (face_value / PU)^(365 / dias_corridos) − 1

- Exactly one input is typed, the rate or the PU; the other is calculated.
- Calendar days include weekends and holidays; there is no holiday calendar (OQ-7).
- The rate is an annual fraction: 0.10 = 10% a.a.
- `QuoteValidator` is the one validation of a typed quote, which Ledger and Prices call through
  `pricing.public` with their own field names before pricing; the calculator runs it too.
- Precision (OQ-3): the 34-digit, half-up context of `di1.shared.decimals`. A calculated PU is
  returned as stored (10 places), a calculated rate as stored (12 places). A typed value with more
  places is rejected, never rounded, and is returned as typed.
- Bounds are only the schema's (OQ-14): PU > 0, rate > −1. A calculated value that would be stored
  outside them is rejected too.
- Maturity (OQ-1): on the maturity date (0 days) the PU is typed and the rate is 0; a typed rate
  is rejected. A reference date after the maturity is rejected.

"Today" checks belong to the callers (Ledger, Prices).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, Overflow
from typing import NoReturn

from di1.modules.pricing.domain.futures.model import (
    FuturesTerms,
    InputKind,
    Price,
    Quote,
)
from di1.shared.calendar import DAYS_PER_YEAR, calendar_days
from di1.shared.decimals import (
    PU_PLACES,
    RATE_PLACES,
    financial_context,
    fits_places,
    quantize_pu,
    quantize_rate,
)
from di1.shared.errors import DomainError, ErrorCode, ErrorDetail


@dataclass(frozen=True, slots=True)
class QuoteFields:
    """The fields a quote's errors are reported on: Pricing's own names by default; a caller
    passes its request's names, so its client keys each message on the right input (OQ-34)."""

    reference_date: str = "reference_date"
    pu: str = "pu"
    rate: str = "rate"

    def from_pricing(self, field: str | None) -> str | None:
        """This caller's name for a field the calculator reported on Pricing's names; any other
        field, such as ``asset_id``, keeps its name."""
        if field is None:
            return None
        return {
            _PRICING_FIELDS.reference_date: self.reference_date,
            _PRICING_FIELDS.pu: self.pu,
            _PRICING_FIELDS.rate: self.rate,
        }.get(field, field)


_PRICING_FIELDS = QuoteFields()


@dataclass(frozen=True, slots=True)
class QuoteValidator:
    """The one validation of a DI1 quote typed as a PU or a rate (spec §4.1; OQ-1, OQ-3, OQ-14).

    Ledger and Prices call it before pricing, so their requests report every problem at once, and
    the calculator runs it again on its own input: one rule, one set of messages.
    """

    fields: QuoteFields = _PRICING_FIELDS

    def __call__(
        self,
        kind: InputKind,
        *,
        pu: Decimal | None,
        rate: Decimal | None,
        reference_date: date,
        maturity_date: date | None,
    ) -> tuple[Decimal | None, tuple[ErrorDetail, ...]]:
        """The typed value, or ``None``, and every problem found. ``maturity_date`` is ``None``
        when the caller knows no contract; then only the typed values are checked."""
        errors: list[ErrorDetail] = []
        if maturity_date is not None and reference_date > maturity_date:
            errors.append(
                ErrorDetail(
                    ErrorCode.CONTRACT_MATURED,
                    "O contrato já venceu nesta data.",
                    self.fields.reference_date,
                )
            )
        elif kind is InputKind.RATE and reference_date == maturity_date:
            # No rate is typed on the maturity date: one message says so. A missing or invalid
            # rate, or "informe apenas a taxa" for a PU sent too, would contradict it.
            return None, (_invalid("Na data de vencimento informe o PU.", self.fields.rate),)
        if kind is InputKind.PU:
            typed, other = pu, rate
            typed_field, other_field = self.fields.pu, self.fields.rate
            missing, only, places = "Informe o PU.", "Informe apenas o PU, sem a taxa.", PU_PLACES
        else:
            typed, other = rate, pu
            typed_field, other_field = self.fields.rate, self.fields.pu
            missing, only, places = (
                "Informe a taxa.",
                "Informe apenas a taxa, sem o PU.",
                RATE_PLACES,
            )
        if other is not None:
            errors.append(_invalid(only, other_field))
        if typed is None:
            errors.append(_invalid(missing, typed_field))
        elif not typed.is_finite():
            errors.append(_invalid("Informe um número válido.", typed_field))
        elif not fits_places(typed, places):
            errors.append(_invalid(f"Use no máximo {places} casas decimais.", typed_field))
        elif kind is InputKind.PU and typed <= 0:
            errors.append(_invalid("O PU deve ser maior que zero.", typed_field))
        elif kind is InputKind.RATE and typed <= -1:
            errors.append(_invalid("A taxa deve ser maior que −100%.", typed_field))
        return (None if errors else typed), tuple(errors)


_validate_quote = QuoteValidator()


class DI1Calculator:
    """Stateless; one instance can be shared."""

    def calculate(self, terms: FuturesTerms, reference_date: date, quote: Quote) -> Price:
        typed_pu = quote.kind is InputKind.PU
        _, errors = _validate_quote(
            quote.kind,
            pu=quote.value if typed_pu else None,
            rate=None if typed_pu else quote.value,
            reference_date=reference_date,
            maturity_date=terms.maturity_date,
        )
        if errors:
            raise DomainError(*errors)
        days = calendar_days(reference_date, terms.maturity_date)
        if typed_pu:
            pu = quote.value
            rate = (
                quantize_rate(Decimal(0))
                if days == 0
                else _rate_from_pu(pu, days, terms.face_value)
            )
        else:
            rate = quote.value
            pu = _pu_from_rate(rate, days, terms.face_value)
        return Price(pu=pu, rate=rate, input_kind=quote.kind)


def _invalid(message: str, field: str) -> ErrorDetail:
    return ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field)


def _refuse(message: str, field: str) -> NoReturn:
    raise DomainError(_invalid(message, field))


_PU_ROUNDS_TO_ZERO = "A taxa resulta em um PU que arredonda para zero."


def _pu_from_rate(rate: Decimal, days: int, face_value: Decimal) -> Decimal:
    with financial_context():
        try:
            discount = (1 + rate) ** (Decimal(days) / DAYS_PER_YEAR)
        except Overflow:
            _refuse(_PU_ROUNDS_TO_ZERO, "rate")  # a discount factor that large gives a PU of ~0
        try:
            pu = face_value / discount
        except Overflow:
            _refuse("A taxa resulta em um PU fora do limite de cálculo.", "rate")
    stored = quantize_pu(pu)
    if stored <= 0:
        _refuse(_PU_ROUNDS_TO_ZERO, "rate")
    return stored


def _rate_from_pu(pu: Decimal, days: int, face_value: Decimal) -> Decimal:
    try:
        with financial_context():
            rate = (face_value / pu) ** (DAYS_PER_YEAR / Decimal(days)) - 1
    except Overflow:
        _refuse("O PU resulta em uma taxa fora do limite de cálculo.", "pu")
    stored = quantize_rate(rate)
    if stored <= -1:
        _refuse("O PU resulta em uma taxa que arredonda para −100%.", "pu")
    return stored
