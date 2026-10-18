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

from di1.modules.pricing.domain.errors import ContractMaturedError, InvalidPricingInputError
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


class DI1Calculator:
    """Stateless; one instance can be shared."""

    def calculate(self, terms: FuturesTerms, reference_date: date, quote: Quote) -> Price:
        days = calendar_days(reference_date, terms.maturity_date)
        if days < 0:
            raise ContractMaturedError(
                "the reference date is after the contract's maturity", field="reference_date"
            )
        if quote.kind is InputKind.RATE:
            rate = _typed_rate(quote.value)
            if days == 0:
                raise InvalidPricingInputError(
                    "on the maturity date the PU is typed, not the rate", field="rate"
                )
            pu = _pu_from_rate(rate, days, terms.face_value)
        else:
            pu = _typed_pu(quote.value)
            if days == 0:
                rate = quantize_rate(Decimal(0))
            else:
                rate = _rate_from_pu(pu, days, terms.face_value)
        return Price(
            pu=pu,
            rate=rate,
            input_kind=quote.kind,
        )


def _typed_rate(rate: Decimal) -> Decimal:
    if not fits_places(rate, RATE_PLACES):
        raise InvalidPricingInputError(
            f"a typed rate has at most {RATE_PLACES} decimal places", field="rate"
        )
    if rate <= -1:
        raise InvalidPricingInputError("the rate must be greater than -1", field="rate")
    return rate


def _typed_pu(pu: Decimal) -> Decimal:
    if not fits_places(pu, PU_PLACES):
        raise InvalidPricingInputError(
            f"a typed PU has at most {PU_PLACES} decimal places", field="pu"
        )
    if pu <= 0:
        raise InvalidPricingInputError("the PU must be positive", field="pu")
    return pu


def _pu_from_rate(rate: Decimal, days: int, face_value: Decimal) -> Decimal:
    rounds_to_zero = InvalidPricingInputError(
        "the rate gives a PU that rounds to zero at 10 places", field="rate"
    )
    with financial_context():
        try:
            discount = (1 + rate) ** (Decimal(days) / DAYS_PER_YEAR)
        except Overflow as exc:
            raise rounds_to_zero from exc  # a discount factor that large gives a PU of ~0
        try:
            pu = face_value / discount
        except Overflow as exc:
            raise InvalidPricingInputError(
                "the rate gives a PU beyond the calculation's range", field="rate"
            ) from exc
    stored = quantize_pu(pu)
    if stored <= 0:
        raise rounds_to_zero
    return stored


def _rate_from_pu(pu: Decimal, days: int, face_value: Decimal) -> Decimal:
    try:
        with financial_context():
            rate = (face_value / pu) ** (DAYS_PER_YEAR / Decimal(days)) - 1
    except Overflow as exc:
        raise InvalidPricingInputError(
            "the PU gives a rate beyond the calculation's range", field="pu"
        ) from exc
    stored = quantize_rate(rate)
    if stored <= -1:
        raise InvalidPricingInputError(
            "the PU gives a rate that rounds to -1 at 12 places", field="pu"
        )
    return stored
