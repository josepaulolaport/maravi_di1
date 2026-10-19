"""Catalogue search: a case- and accent-insensitive substring (user, 2026-10-19).

The catalogue is small, so the fold runs in Python rather than through PostgreSQL's ``unaccent``,
which the schema does not install.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable


def fold(text: str) -> str:
    """``text`` without accents, case-folded: "Depósitos" → "depositos"."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(values: Iterable[str | None], search: str | None) -> bool:
    """Whether ``search`` occurs in any of ``values``; no search (or a blank one) matches all."""
    needle = fold(search.strip()) if search else ""
    if not needle:
        return True
    return any(value is not None and needle in fold(value) for value in values)
