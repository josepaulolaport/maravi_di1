"""Which value of a PU/rate pair the user typed (spec §4.1; schema ``input_kind``).

Pricing, Ledger and Prices all compute on it in their domain code, so it is defined once here.
Standard library only: domain code imports this module.
"""

from __future__ import annotations

from enum import StrEnum


class InputKind(StrEnum):
    """The authoritative input; the other value of the pair is calculated (DC/365)."""

    PU = "PU"
    RATE = "RATE"
