"""The value lists of ``docs/schema.sql``'s ``CHECK (<column> IN (...))`` constraints, so an
enum can be compared with the column it is stored in: by constraint name (`check_values`) or by
table and column (`column_values`, which also finds a list inside a compound CHECK)."""

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


def column_values(table: str, column: str) -> set[str]:
    """The values every ``<column> IN (...)`` of ``table``'s CREATE TABLE allows; all must agree."""
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    start = schema.index(f"CREATE TABLE {table} (")
    body = schema[start : schema.index("\n);", start)]
    lists = re.findall(rf"\b{column} IN \(([^)]*)\)", body)
    assert lists, f"{table}.{column} has no IN check"
    sets = [set(re.findall(r"'([^']*)'", values)) for values in lists]
    assert all(values == sets[0] for values in sets), f"{table}.{column} checks disagree"
    return sets[0]
