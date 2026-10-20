"""The value lists of ``docs/schema.sql``'s ``CHECK (<column> IN (...))`` constraints, so an
enum can be compared with the column it is stored in."""

from __future__ import annotations

import re
from pathlib import Path

SCHEMA_SQL = Path(__file__).resolve().parents[3] / "docs" / "schema.sql"


def check_values(constraint: str) -> set[str]:
    """The quoted values of the named ``CHECK (... IN (...))`` constraint."""
    match = re.search(
        rf"CONSTRAINT {re.escape(constraint)} CHECK \(\w+ IN \(([^)]*)\)\)",
        SCHEMA_SQL.read_text(encoding="utf-8"),
    )
    assert match is not None, f"no CHECK ... IN constraint {constraint} in {SCHEMA_SQL}"
    return set(re.findall(r"'([^']*)'", match.group(1)))
