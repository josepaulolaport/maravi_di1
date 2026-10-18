"""Errors every pricing family raises (interfaces "Errors")."""

from __future__ import annotations

from typing import ClassVar


class PricingError(Exception):
    """A pricing request that is refused. ``code`` is the error-catalogue code; ``field`` names
    the offending input."""

    code: ClassVar[str]

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


class InvalidPricingInputError(PricingError):
    """Out of bounds, too many decimals, not finite, or not allowed on this date."""

    code = "VALIDATION_ERROR"


class ContractMaturedError(PricingError):
    """The reference date is after the contract's maturity (OQ-1)."""

    code = "CONTRACT_MATURED"
