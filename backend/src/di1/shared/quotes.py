"""Where a reference observation came from (spec §5).

Kept in ``shared`` only until Prices owns it in its domain (staff review §5).
"""

from __future__ import annotations

from enum import StrEnum


class PriceSource(StrEnum):
    """Where a reference observation came from. MANUAL wins over B3 on the same date (spec §5)."""

    MANUAL = "MANUAL"
    B3 = "B3"
