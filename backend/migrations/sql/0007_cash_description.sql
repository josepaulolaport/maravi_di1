-- OQ-51: an aporte or a retirada may carry an optional description (challenge §4.2), stored
-- trimmed and NULL when blank by Ledger, at most 200 characters. A trade has none. Existing
-- entries get NULL. Entries are never edited (OQ-24), so neither is the description.
ALTER TABLE ledger.entries
    ADD COLUMN description VARCHAR(200),
    ADD CONSTRAINT entries_description_cash_only CHECK (type = 'CASH' OR description IS NULL);
