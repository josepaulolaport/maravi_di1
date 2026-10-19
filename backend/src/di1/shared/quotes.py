"""A typed PU or rate, and the callable that validates one (spec §4.1).

Pricing owns the rule (`QuoteValidator`). Ledger and Prices inject it into domain code, which
may import this module and not another module's `public.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from di1.shared.errors import ErrorDetail
from di1.shared.input_kind import InputKind


class PriceSource(StrEnum):
    """Where a reference observation came from. MANUAL wins over B3 on the same date (spec §5)."""

    MANUAL = "MANUAL"
    B3 = "B3"


@dataclass(frozen=True, slots=True)
class Quote:
    """What was typed: a rate or a PU, the single authoritative input."""

    kind: InputKind
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError(f"a quote must be a Decimal, got {type(self.value).__name__}")


class QuoteRule(Protocol):
    """`(kind, pu, rate, reference_date, maturity_date) -> (typed value | None, errors)`.

    Production passes `pricing.public.QuoteValidator`.
    """

    def __call__(
        self,
        kind: InputKind,
        *,
        pu: Decimal | None,
        rate: Decimal | None,
        reference_date: date,
        maturity_date: date | None,
    ) -> tuple[Decimal | None, Sequence[ErrorDetail]]: ...
