"""Decimal precision and rounding for all financial arithmetic (OQ-3; spec §4.1).

- One context: 34 significant digits, ``ROUND_HALF_UP`` (halfway away from zero).
- Storage: a calculated PU keeps 10 decimal places, a calculated rate 12.
- A typed PU or rate with more decimals than stored is rejected, never rounded. `fits_places`
  answers that question; the module that validates the input raises its own error.
- Money is kept exact and rounded to 2 places only for display, in the frontend.
- Storing never fails for a finite value: the schema columns are unbounded ``NUMERIC`` and the
  only value bounds are the schema's (OQ-14), so rounding uses a context wide enough for the value.
  It never yields a negative zero.
- Values leave the backend in plain notation (`to_plain`), never exponent form (CLAUDE.md §2).
- A float mixed into financial arithmetic raises ``FloatOperation`` (CLAUDE.md §2: never float).

Decimals are built from ``str``, never from ``float``. Standard library only: domain code imports
this module.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    localcontext,
)

DECIMAL_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_UP,
    traps=[InvalidOperation, DivisionByZero, Overflow, FloatOperation],
)
"""The decimal context for financial arithmetic (OQ-3). Use it through `financial_context`, which
works on a copy; never mutate this object."""

PU_PLACES = 10
"""Decimal places of a stored PU (OQ-3)."""

RATE_PLACES = 12
"""Decimal places of a stored rate; the rate is a fraction, 0.135 = 13.5% a.a. (OQ-3)."""

ZERO = Decimal(0)
"""The unsigned zero every module starts its sums from."""


def financial_context() -> AbstractContextManager[Context]:
    """``with financial_context(): ...`` runs the block in `DECIMAL_CONTEXT` and then restores
    the caller's context."""
    return localcontext(DECIMAL_CONTEXT)


def fits_places(value: Decimal, places: int) -> bool:
    """Whether a typed value is finite and has at most ``places`` decimal places. Trailing zeros
    count, since they were typed (``0.10000000000000`` has 14 places)."""
    if not value.is_finite():
        return False
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # finite values have an integer exponent
    return exponent >= -places


def unsigned(value: Decimal) -> Decimal:
    """``value`` with the sign of a zero dropped (``-0.00`` → ``0.00``); any other value as is.
    Arithmetic can yield a negative zero, which would reach the client as ``"-0"``."""
    return value.copy_abs() if value.is_zero() else value


def _quantize(value: Decimal, places: int) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"cannot store a value that is not finite: {value}")
    # Wide enough for every integer digit plus the stored places, never below 34: rounding then
    # only happens at the stored place. A private context keeps the shared one untouched.
    context = DECIMAL_CONTEXT.copy()
    context.prec = max(DECIMAL_CONTEXT.prec, value.adjusted() + places + 2)
    result = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP, context=context)
    return unsigned(result)


def quantize_pu(value: Decimal) -> Decimal:
    """A calculated PU as stored: 10 places, half-up (OQ-3)."""
    return _quantize(value, PU_PLACES)


def quantize_rate(value: Decimal) -> Decimal:
    """A calculated rate as stored: 12 places, half-up (OQ-3)."""
    return _quantize(value, RATE_PLACES)


def to_plain(value: Decimal) -> str:
    """The value in plain notation, as JSON and the frontend expect (``0E-12`` →
    ``0.000000000000``, ``1E+2`` → ``100``)."""
    if not value.is_finite():
        raise ValueError(f"cannot serialise a value that is not finite: {value}")
    return format(value, "f")
