-- OQ-21: cash and positions become two separately processable chains.
-- Run with no job active (none DISPATCHED, RUNNING or CANCELLING): staged rows are discarded.

-- Requests: a scope, and the revisions captured per input. Existing requests covered both chains.
ALTER TABLE processing.requests ADD COLUMN scope VARCHAR(16);
UPDATE processing.requests SET scope = 'ALL';
ALTER TABLE processing.requests ALTER COLUMN scope SET NOT NULL;
ALTER TABLE processing.requests
    ADD CONSTRAINT requests_scope_check CHECK (scope IN ('CASH','POSITIONS','ALL'));
ALTER TABLE processing.requests RENAME COLUMN ledger_revision_at_start TO trades_revision_at_start;
ALTER TABLE processing.requests ADD COLUMN cash_movements_revision_at_start BIGINT;
UPDATE processing.requests SET cash_movements_revision_at_start = trades_revision_at_start;

-- Calculation state: the ledger revision splits into trades and cash movements, both starting from
-- the old value; the accounting marker splits into the cash and the positions markers.
ALTER TABLE processing.calculation_state DROP CONSTRAINT calculation_state_ledger_revision_check;
ALTER TABLE processing.calculation_state RENAME COLUMN ledger_revision TO trades_revision;
ALTER TABLE processing.calculation_state
    ADD CONSTRAINT calculation_state_trades_revision_check CHECK (trades_revision >= 0);
ALTER TABLE processing.calculation_state
    ADD COLUMN cash_movements_revision BIGINT NOT NULL DEFAULT 0 CHECK (cash_movements_revision >= 0);
UPDATE processing.calculation_state SET cash_movements_revision = trades_revision;
ALTER TABLE processing.calculation_state RENAME COLUMN accounting_dirty_from TO cash_dirty_from;
ALTER TABLE processing.calculation_state ADD COLUMN positions_dirty_from DATE;
UPDATE processing.calculation_state SET positions_dirty_from = cash_dirty_from;

-- Published cash has no components to backfill from: drop it, mark cash stale from the first
-- published day and leave AUM unavailable until the cash chain is processed again.
UPDATE processing.calculation_state
    SET cash_dirty_from = LEAST(cash_dirty_from, (SELECT min(metric_date) FROM portfolio.portfolio_metrics));
ALTER TABLE portfolio.portfolio_metrics DROP CONSTRAINT portfolio_metrics_aum_consistency;
UPDATE portfolio.portfolio_metrics SET aum = NULL;
ALTER TABLE portfolio.portfolio_metrics DROP COLUMN cash_balance;
ALTER TABLE portfolio.portfolio_metrics
    ADD CONSTRAINT portfolio_metrics_aum_needs_market_value CHECK (aum IS NULL OR positions_market_value IS NOT NULL);
DELETE FROM portfolio.staged_positions;
DELETE FROM portfolio.staged_portfolio_metrics;
ALTER TABLE portfolio.staged_portfolio_metrics DROP COLUMN cash_balance;

-- The cash chain (OQ-21), one row per processed calendar day:
--   cash_balance[D] = cash_balance[D-1] + trades_cash_flow[D] + deposits[D] - withdrawals[D]
--   trades_cash_flow[D] = -sum(signed_quantity * execution_pu) over the day's active trades
-- Owned by Portfolio, like the other published and staged tables (OQ-8).
CREATE TABLE portfolio.cash_balances (
    balance_date DATE PRIMARY KEY,
    cash_balance NUMERIC NOT NULL,
    trades_cash_flow NUMERIC NOT NULL,
    deposits NUMERIC NOT NULL,
    withdrawals NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cash_balances_movements_nonnegative CHECK (deposits >= 0 AND withdrawals >= 0)
);
CREATE TABLE portfolio.staged_cash_balances (
    request_id UUID NOT NULL REFERENCES processing.requests(id) ON DELETE CASCADE,
    balance_date DATE NOT NULL,
    cash_balance NUMERIC NOT NULL,
    trades_cash_flow NUMERIC NOT NULL,
    deposits NUMERIC NOT NULL,
    withdrawals NUMERIC NOT NULL,
    CONSTRAINT staged_cash_balances_movements_nonnegative CHECK (deposits >= 0 AND withdrawals >= 0),
    PRIMARY KEY(request_id, balance_date)
);
