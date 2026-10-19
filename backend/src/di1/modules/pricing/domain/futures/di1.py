"""DI1 pricing: PU ↔ rate, DC/365 with calendar days (spec §4.1; interfaces "Pricing").

    PU   = face_value / (1 + taxa)^(dias_corridos / 365)
    taxa = (face_value / PU)^(365 / dias_corridos) − 1

- Exactly one input is typed, the rate or the PU; the other is calculated.
- Calendar days include weekends and holidays; there is no holiday calendar (OQ-7).
- The rate is an annual fraction: 0.10 = 10% a.a.
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


class DI1Calculator:
    """Stateless; one instance can be shared."""

    def calculate(self, terms: FuturesTerms, reference_date: date, quote: Quote) -> Price:
        days = calendar_days(reference_date, terms.maturity_date)
        if days < 0:
            raise DomainError(
                ErrorDetail(
                    ErrorCode.CONTRACT_MATURED,
                    "A data é posterior ao vencimento do contrato.",
                    "reference_date",
                )
            )
        if quote.kind is InputKind.RATE:
            rate = _typed_rate(quote.value)
            if days == 0:
                _invalid("No vencimento, informe o PU, não a taxa.", "rate")
            pu = _pu_from_rate(rate, days, terms.face_value)
        else:
            pu = _typed_pu(quote.value)
            if days == 0:
                rate = quantize_rate(Decimal(0))
            else:
                rate = _rate_from_pu(pu, days, terms.face_value)
        return Price(pu=pu, rate=rate, input_kind=quote.kind)


def _invalid(message: str, field: str) -> NoReturn:
    raise DomainError(ErrorDetail(ErrorCode.VALIDATION_ERROR, message, field))


def _typed_rate(rate: Decimal) -> Decimal:
    if not rate.is_finite():
        _invalid("A taxa deve ser um número finito.", "rate")
    if not fits_places(rate, RATE_PLACES):
        _invalid(f"A taxa aceita no máximo {RATE_PLACES} casas decimais.", "rate")
    if rate <= -1:
        _invalid("A taxa deve ser maior que -1.", "rate")
    return rate


def _typed_pu(pu: Decimal) -> Decimal:
    if not pu.is_finite():
        _invalid("O PU deve ser um número finito.", "pu")
    if not fits_places(pu, PU_PLACES):
        _invalid(f"O PU aceita no máximo {PU_PLACES} casas decimais.", "pu")
    if pu <= 0:
        _invalid("O PU deve ser maior que zero.", "pu")
    return pu


_PU_ROUNDS_TO_ZERO = "A taxa resulta em um PU que arredonda para zero."


def _pu_from_rate(rate: Decimal, days: int, face_value: Decimal) -> Decimal:
    with financial_context():
        try:
            discount = (1 + rate) ** (Decimal(days) / DAYS_PER_YEAR)
        except Overflow:
            _invalid(_PU_ROUNDS_TO_ZERO, "rate")  # a discount factor that large gives a PU of ~0
        try:
            pu = face_value / discount
        except Overflow:
            _invalid("A taxa resulta em um PU fora do limite de cálculo.", "rate")
    stored = quantize_pu(pu)
    if stored <= 0:
        _invalid(_PU_ROUNDS_TO_ZERO, "rate")
    return stored


def _rate_from_pu(pu: Decimal, days: int, face_value: Decimal) -> Decimal:
    try:
        with financial_context():
            rate = (face_value / pu) ** (DAYS_PER_YEAR / Decimal(days)) - 1
    except Overflow:
        _invalid("O PU resulta em uma taxa fora do limite de cálculo.", "pu")
    stored = quantize_rate(rate)
    if stored <= -1:
        _invalid("O PU resulta em uma taxa que arredonda para -1.", "pu")
    return stored
