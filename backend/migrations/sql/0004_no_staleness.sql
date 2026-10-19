-- OQ-31: nothing is stale any more. A write saves only its fact; a date's results change only
-- when the user processes it again. The date statuses are renamed (FRESH implied freshness):
-- PROCESSED, PROCESSED_WITH_ISSUES, RUNNING, FAILED; no row is "not processed".

-- The day before is now checked per date and fails the run (CASH_ or POSITIONS_PREDECESSOR_MISSING),
-- so STALE_PREDECESSOR issues and the issue chain, which existed only for them, go.
-- A date that carried a STALE_PREDECESSOR issue was computed on a day before that was not
-- processed: under OQ-31 that date fails, so its chain becomes FAILED first.
UPDATE processing.date_status AS s SET
    portfolio = CASE WHEN EXISTS (SELECT 1 FROM processing.issues AS i
                                  WHERE i.issue_type = 'STALE_PREDECESSOR' AND i.affected_date = s.date
                                    AND i.chain = 'POSITIONS') AND s.portfolio = 'STALE'
                     THEN 'FAILED' ELSE s.portfolio END,
    cash = CASE WHEN EXISTS (SELECT 1 FROM processing.issues AS i
                             WHERE i.issue_type = 'STALE_PREDECESSOR' AND i.affected_date = s.date
                               AND i.chain = 'CASH') AND s.cash = 'STALE'
                THEN 'FAILED' ELSE s.cash END;
DELETE FROM processing.issues WHERE issue_type = 'STALE_PREDECESSOR';
DROP INDEX processing.issues_unique_per_request_idx;
ALTER TABLE processing.issues
    DROP CONSTRAINT issues_chain_for_stale_predecessor,
    DROP CONSTRAINT issues_chain_check,
    DROP COLUMN chain;
CREATE UNIQUE INDEX issues_unique_per_request_idx ON processing.issues (request_id, asset_id, affected_date, required_price_date, issue_type) NULLS NOT DISTINCT;

-- The new names. A STALE chain with a published row keeps its figures, so it is processed: with
-- issues when those figures have them (a missing price or an expired open position), as 0003
-- derived them. A STALE chain without a published row could only come from FAILED (0003 marked
-- every date that had a status), so it is FAILED again. The cash chain raises no issues (OQ-31).
ALTER TABLE processing.date_status
    DROP CONSTRAINT date_status_portfolio_check,
    DROP CONSTRAINT date_status_cash_check,
    DROP CONSTRAINT date_status_portfolio_previous_check,
    DROP CONSTRAINT date_status_cash_previous_check;
UPDATE processing.date_status AS s SET
    portfolio = CASE s.portfolio
        WHEN 'FRESH' THEN 'PROCESSED'
        WHEN 'FRESH_WITH_ISSUES' THEN 'PROCESSED_WITH_ISSUES'
        WHEN 'STALE' THEN CASE
            WHEN NOT EXISTS (SELECT 1 FROM portfolio.portfolio_metrics AS pm WHERE pm.metric_date = s.date)
                THEN 'FAILED'
            WHEN EXISTS (SELECT 1 FROM portfolio.portfolio_metrics AS pm
                         WHERE pm.metric_date = s.date
                           AND (pm.valuation_status = 'MISSING' OR pm.pnl_status = 'MISSING'))
                 OR EXISTS (SELECT 1 FROM processing.issues AS i
                            WHERE i.issue_type = 'EXPIRED_OPEN_POSITION' AND i.affected_date = s.date)
                THEN 'PROCESSED_WITH_ISSUES'
            ELSE 'PROCESSED' END
        ELSE s.portfolio END,
    portfolio_previous = CASE s.portfolio_previous
        WHEN 'FRESH' THEN 'PROCESSED'
        WHEN 'FRESH_WITH_ISSUES' THEN 'PROCESSED_WITH_ISSUES'
        WHEN 'STALE' THEN CASE
            WHEN NOT EXISTS (SELECT 1 FROM portfolio.portfolio_metrics AS pm WHERE pm.metric_date = s.date)
                THEN 'FAILED'
            WHEN EXISTS (SELECT 1 FROM portfolio.portfolio_metrics AS pm
                         WHERE pm.metric_date = s.date
                           AND (pm.valuation_status = 'MISSING' OR pm.pnl_status = 'MISSING'))
                 OR EXISTS (SELECT 1 FROM processing.issues AS i
                            WHERE i.issue_type = 'EXPIRED_OPEN_POSITION' AND i.affected_date = s.date)
                THEN 'PROCESSED_WITH_ISSUES'
            ELSE 'PROCESSED' END
        ELSE s.portfolio_previous END,
    cash = CASE s.cash
        WHEN 'FRESH' THEN 'PROCESSED'
        WHEN 'FRESH_WITH_ISSUES' THEN 'PROCESSED'
        WHEN 'STALE' THEN CASE
            WHEN EXISTS (SELECT 1 FROM portfolio.cash_balances AS cb WHERE cb.balance_date = s.date)
                THEN 'PROCESSED' ELSE 'FAILED' END
        ELSE s.cash END,
    cash_previous = CASE s.cash_previous
        WHEN 'FRESH' THEN 'PROCESSED'
        WHEN 'FRESH_WITH_ISSUES' THEN 'PROCESSED'
        WHEN 'STALE' THEN CASE
            WHEN EXISTS (SELECT 1 FROM portfolio.cash_balances AS cb WHERE cb.balance_date = s.date)
                THEN 'PROCESSED' ELSE 'FAILED' END
        ELSE s.cash_previous END;
ALTER TABLE processing.date_status
    ADD CONSTRAINT date_status_portfolio_check CHECK (portfolio IS NULL OR portfolio IN ('PROCESSED','PROCESSED_WITH_ISSUES','RUNNING','FAILED')),
    ADD CONSTRAINT date_status_cash_check CHECK (cash IS NULL OR cash IN ('PROCESSED','PROCESSED_WITH_ISSUES','RUNNING','FAILED')),
    ADD CONSTRAINT date_status_portfolio_previous_check CHECK (portfolio_previous IS NULL OR (portfolio = 'RUNNING' AND portfolio_previous IN ('PROCESSED','PROCESSED_WITH_ISSUES','FAILED'))),
    ADD CONSTRAINT date_status_cash_previous_check CHECK (cash_previous IS NULL OR (cash = 'RUNNING' AND cash_previous IN ('PROCESSED','PROCESSED_WITH_ISSUES','FAILED')));

-- When a run last committed each chain for the date ("Processado em …"); NULL if never. Backfilled
-- from the published rows' updated_at, which a run sets when it writes the date; for the
-- positions chain this is an approximation, since a CASH run also rewrites portfolio_metrics
-- when it recomputes the AUM. A chain with no status gets no time.
ALTER TABLE processing.date_status
    ADD COLUMN portfolio_processed_at TIMESTAMPTZ,
    ADD COLUMN cash_processed_at TIMESTAMPTZ;
UPDATE processing.date_status AS s SET
    portfolio_processed_at = CASE WHEN s.portfolio IS NOT NULL THEN
        (SELECT pm.updated_at FROM portfolio.portfolio_metrics AS pm WHERE pm.metric_date = s.date) END,
    cash_processed_at = CASE WHEN s.cash IS NOT NULL THEN
        (SELECT cb.updated_at FROM portfolio.cash_balances AS cb WHERE cb.balance_date = s.date) END;
