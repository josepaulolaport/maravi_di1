"""The Alembic revisions build exactly what `docs/schema.sql` builds (skill `db-migration`).

`docs/schema.sql` is the complete schema; each revision runs its own reviewed SQL. Upgrading to
head must give the same columns (type, nullability, default), constraints and indexes as running
`docs/schema.sql` on an empty database, and a downgrade must give back the previous revision's
catalog. Column order is deliberately not compared: PostgreSQL appends added columns and cannot
reorder them, so nothing may rely on positional column order. Comments, triggers, functions and
sequences are not compared; the schema has none of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command

from tests.integration.alembic_support import (
    alembic_config,
    catalog,
    database,
    database_url,
    execute,
)

__all__ = ["database_url"]

BACKEND = Path(__file__).resolve().parents[2]
SCHEMA_SQL = BACKEND.parent / "docs" / "schema.sql"
PARTS = ("columns", "constraints", "indexes")


def _catalog_of_sql(sql: str) -> dict[str, set[tuple[Any, ...]]]:
    with database() as url:
        execute(url, sql)
        return catalog(url)


def test_upgrade_to_head_builds_exactly_the_documented_schema(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")

    migrated = catalog(database_url)
    documented = _catalog_of_sql(SCHEMA_SQL.read_text())
    for part in PARTS:
        assert migrated[part] == documented[part], part


@pytest.mark.parametrize("revision", ["0001", "0002", "0003", "0004", "0005", "0006"])
def test_downgrade_from_head_gives_back_the_revisions_schema(
    database_url: str, revision: str
) -> None:
    command.upgrade(alembic_config(database_url), "head")
    command.downgrade(alembic_config(database_url), revision)

    downgraded = catalog(database_url)
    with database() as reference_url:
        command.upgrade(alembic_config(reference_url), revision)
        upgraded = catalog(reference_url)
    for part in PARTS:
        assert downgraded[part] == upgraded[part], part
