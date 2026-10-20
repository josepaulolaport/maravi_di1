"""Revision 0005: ledger entries are hard-deleted (OQ-32).

The catalog equivalence with `docs/schema.sql` is in `test_migrations_match_schema.py`. Here: the
upgrade physically deletes the entries that were soft-deleted and drops the deletion columns, and
the downgrade brings the columns back empty.
"""

from __future__ import annotations

from alembic import command

from tests.support.db import alembic_config, execute, fetch

ENTRIES = (
    "INSERT INTO ledger.entries (type, entry_date, entry_time, cash_amount, deleted_at,"
    " deletion_batch_id) VALUES"
    " ('CASH', '2026-10-01', '10:00', 1000, NULL, NULL),"
    " ('CASH', '2026-10-01', '11:00', 500, now(), gen_random_uuid()),"
    " ('CASH', '2026-10-02', '09:00', -200, now(), NULL)"
)
DELETION_COLUMNS = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ledger'"
    " AND table_name = 'entries' AND column_name IN ('deleted_at', 'deletion_batch_id')"
    " ORDER BY 1"
)


def test_upgrade_deletes_the_soft_deleted_entries_and_their_columns(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "0004")
    execute(database_url, ENTRIES)

    command.upgrade(alembic_config(database_url), "0005")

    assert fetch(database_url, DELETION_COLUMNS) == []
    assert fetch(
        database_url, "SELECT entry_time::text, cash_amount::text FROM ledger.entries"
    ) == [("10:00:00", "1000.00")]


def test_downgrade_brings_the_columns_back_empty_without_the_deleted_entries(
    database_url: str,
) -> None:
    command.upgrade(alembic_config(database_url), "0004")
    execute(database_url, ENTRIES)
    command.upgrade(alembic_config(database_url), "0005")

    command.downgrade(alembic_config(database_url), "0004")

    assert fetch(database_url, DELETION_COLUMNS) == [("deleted_at",), ("deletion_batch_id",)]
    assert fetch(
        database_url, "SELECT entry_time::text, deleted_at, deletion_batch_id FROM ledger.entries"
    ) == [("10:00:00", None, None)]
