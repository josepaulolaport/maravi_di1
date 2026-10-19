-- Back to one accounting chain (0001). The revision refuses this while a job is active, or while
-- published cash, published metrics, staged rows, cash issues or CASH/POSITIONS-scoped requests
-- exist, unless `-x allow_data_loss=true` is given.
DROP TABLE portfolio.staged_cash_balances;
DROP TABLE portfolio.cash_balances;

DELETE FROM portfolio.staged_positions;
DELETE FROM portfolio.staged_portfolio_metrics;
ALTER TABLE portfolio.staged_portfolio_metrics ADD COLUMN cash_balance NUMERIC NOT NULL;

-- The single-row AUM check returns; published metrics have no cash to satisfy it, so they go and
-- accounting is stale from their first day.
UPDATE processing.calculation_state
    SET cash_dirty_from = LEAST(cash_dirty_from, positions_dirty_from, (SELECT min(metric_date) FROM portfolio.portfolio_metrics));
DELETE FROM portfolio.portfolio_metrics;
ALTER TABLE portfolio.portfolio_metrics DROP CONSTRAINT portfolio_metrics_aum_needs_market_value;
ALTER TABLE portfolio.portfolio_metrics ADD COLUMN cash_balance NUMERIC NOT NULL;
ALTER TABLE portfolio.portfolio_metrics
    ADD CONSTRAINT portfolio_metrics_aum_consistency CHECK (aum IS NULL OR (positions_market_value IS NOT NULL AND aum = cash_balance + positions_market_value));

ALTER TABLE processing.calculation_state DROP COLUMN positions_dirty_from;
ALTER TABLE processing.calculation_state RENAME COLUMN cash_dirty_from TO accounting_dirty_from;
-- The sum never decreases and differs from any captured value once either input changed.
UPDATE processing.calculation_state SET trades_revision = trades_revision + cash_movements_revision;
UPDATE processing.requests
    SET trades_revision_at_start = trades_revision_at_start + cash_movements_revision_at_start;
ALTER TABLE processing.calculation_state DROP COLUMN cash_movements_revision;
ALTER TABLE processing.calculation_state DROP CONSTRAINT calculation_state_trades_revision_check;
ALTER TABLE processing.calculation_state RENAME COLUMN trades_revision TO ledger_revision;
ALTER TABLE processing.calculation_state
    ADD CONSTRAINT calculation_state_ledger_revision_check CHECK (ledger_revision >= 0);

DELETE FROM processing.issues WHERE chain = 'CASH';
DROP INDEX processing.issues_unique_per_request_idx;
ALTER TABLE processing.issues DROP CONSTRAINT issues_chain_for_stale_predecessor;
ALTER TABLE processing.issues DROP CONSTRAINT issues_chain_check;
ALTER TABLE processing.issues DROP COLUMN chain;
CREATE UNIQUE INDEX issues_unique_per_request_idx ON processing.issues (request_id, asset_id, affected_date, required_price_date, issue_type) NULLS NOT DISTINCT;

ALTER TABLE processing.requests DROP COLUMN cash_movements_revision_at_start;
ALTER TABLE processing.requests RENAME COLUMN trades_revision_at_start TO ledger_revision_at_start;
ALTER TABLE processing.requests DROP CONSTRAINT requests_scope_check;
ALTER TABLE processing.requests DROP COLUMN scope;
