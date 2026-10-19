-- Back to 0004, soft deletion: the columns come back empty; hard-deleted entries are not rebuilt.
DROP INDEX ledger.entries_trade_asset_date_idx;
DROP INDEX ledger.entries_ordered_idx;
ALTER TABLE ledger.entries
    ADD COLUMN deleted_at TIMESTAMPTZ,
    ADD COLUMN deletion_batch_id UUID,
    ADD CONSTRAINT entries_deletion_batch_tied CHECK (deletion_batch_id IS NULL OR deleted_at IS NOT NULL);
CREATE INDEX entries_ordered_active_idx ON ledger.entries (entry_date, entry_time, seq) WHERE deleted_at IS NULL;
CREATE INDEX entries_asset_date_active_idx ON ledger.entries (asset_id, entry_date, seq) WHERE deleted_at IS NULL AND type = 'TRADE';
