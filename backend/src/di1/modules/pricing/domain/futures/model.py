"""Futures pricing values: a typed rate or PU, the contract terms, the calculated pair
(spec §4; interfaces "Pricing")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from di1.shared.errors import DomainError, ErrorCode, ErrorDetail
from di1.shared.input_kind import InputKind as InputKind  # one definition, shared (W0.3b)


@dataclass(frozen=True, slots=True)
class Quote:
    """What was typed: a rate or a PU, the single authoritative input."""

    kind: InputKind
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError(f"a quote must be a Decimal, got {type(self.value).__name__}")

    @classmethod
    def rate(cls, rate: Decimal) -> Quote:
        return cls(InputKind.RATE, rate)

    @classmethod
    def pu(cls, pu: Decimal) -> Quote:
        return cls(InputKind.PU, pu)


@dataclass(frozen=True, slots=True)
class FuturesTerms:
    """The contract facts pricing needs, read from the instrument and its futures spec (Asset).
    The multiplier is not one of them (OQ-2)."""

    maturity_date: date
    face_value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.face_value, Decimal):
            raise TypeError(f"face value must be a Decimal, got {type(self.face_value).__name__}")
        if not self.face_value.is_finite() or self.face_value <= 0:
            raise DomainError(
                ErrorDetail(
                    ErrorCode.VALIDATION_ERROR,
                    "O valor de face deve ser maior que zero.",
                    "face_value",
                )
            )


@dataclass(frozen=True, slots=True)
class Price:
    """The complete PU and rate pair, with which one was typed: the typed value as typed, the
    other as it is stored."""

    pu: Decimal
    rate: Decimal
    input_kind: InputKind
