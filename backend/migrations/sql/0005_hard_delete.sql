-- OQ-32: ledger entries are hard-deleted. Entries already soft-deleted are deleted for real, and
-- the deletion columns go; the indexes no longer filter on them.
DELETE FROM ledger.entries WHERE deleted_at IS NOT NULL;
DROP INDEX ledger.entries_ordered_active_idx;
DROP INDEX ledger.entries_asset_date_active_idx;
ALTER TABLE ledger.entries
    DROP CONSTRAINT entries_deletion_batch_tied,
    DROP COLUMN deletion_batch_id,
    DROP COLUMN deleted_at;
CREATE INDEX entries_ordered_idx ON ledger.entries (entry_date, entry_time, seq);
CREATE INDEX entries_trade_asset_date_idx ON ledger.entries (asset_id, entry_date, seq) WHERE type = 'TRADE';
