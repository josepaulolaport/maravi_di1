-- Back to the 0004 reference-copy step: PROCESSED* takes the old FRESH* names (0003 reads them as
-- fresh, which OQ-31 data never tracked: accepted for a downgrade); the processing times and the
-- STALE_PREDECESSOR issues are not rebuilt, the issue chain comes back empty.
ALTER TABLE processing.date_status
    DROP COLUMN cash_processed_at,
    DROP COLUMN portfolio_processed_at,
    DROP CONSTRAINT date_status_portfolio_check,
    DROP CONSTRAINT date_status_cash_check,
    DROP CONSTRAINT date_status_portfolio_previous_check,
    DROP CONSTRAINT date_status_cash_previous_check;
UPDATE processing.date_status SET
    portfolio = CASE portfolio WHEN 'PROCESSED' THEN 'FRESH' WHEN 'PROCESSED_WITH_ISSUES' THEN 'FRESH_WITH_ISSUES' ELSE portfolio END,
    portfolio_previous = CASE portfolio_previous WHEN 'PROCESSED' THEN 'FRESH' WHEN 'PROCESSED_WITH_ISSUES' THEN 'FRESH_WITH_ISSUES' ELSE portfolio_previous END,
    cash = CASE cash WHEN 'PROCESSED' THEN 'FRESH' WHEN 'PROCESSED_WITH_ISSUES' THEN 'FRESH_WITH_ISSUES' ELSE cash END,
    cash_previous = CASE cash_previous WHEN 'PROCESSED' THEN 'FRESH' WHEN 'PROCESSED_WITH_ISSUES' THEN 'FRESH_WITH_ISSUES' ELSE cash_previous END;
ALTER TABLE processing.date_status
    ADD CONSTRAINT date_status_portfolio_check CHECK (portfolio IS NULL OR portfolio IN ('FRESH','FRESH_WITH_ISSUES','STALE','RUNNING','FAILED')),
    ADD CONSTRAINT date_status_cash_check CHECK (cash IS NULL OR cash IN ('FRESH','FRESH_WITH_ISSUES','STALE','RUNNING','FAILED')),
    ADD CONSTRAINT date_status_portfolio_previous_check CHECK (portfolio_previous IS NULL OR (portfolio = 'RUNNING' AND portfolio_previous IN ('FRESH','FRESH_WITH_ISSUES','STALE','FAILED'))),
    ADD CONSTRAINT date_status_cash_previous_check CHECK (cash_previous IS NULL OR (cash = 'RUNNING' AND cash_previous IN ('FRESH','FRESH_WITH_ISSUES','STALE','FAILED')));

DROP INDEX processing.issues_unique_per_request_idx;
ALTER TABLE processing.issues
    ADD COLUMN chain VARCHAR(16),
    ADD CONSTRAINT issues_chain_check CHECK (chain IS NULL OR chain IN ('CASH','POSITIONS')),
    ADD CONSTRAINT issues_chain_for_stale_predecessor CHECK ((issue_type = 'STALE_PREDECESSOR') = (chain IS NOT NULL));
CREATE UNIQUE INDEX issues_unique_per_request_idx ON processing.issues (request_id, asset_id, affected_date, required_price_date, issue_type, chain) NULLS NOT DISTINCT;
