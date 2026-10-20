"""Text comparison shared by the searches: case- and accent-insensitive (user, 2026-10-19).

Standard library only: domain code imports this module.
"""

from __future__ import annotations

import unicodedata

__all__ = ["fold"]


def fold(text: str) -> str:
    """``text`` without accents, case-folded: "Depósitos" → "depositos"."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
