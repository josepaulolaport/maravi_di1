-- OQ-23: each date is published in its own transaction and processing.date_status holds the
-- current status of each chain per date; no staging, no dirty markers, no revision counters,
-- no SUPERSEDED. OQ-24: one ledger entry table. OQ-25: reference prices without revisions.
-- The revision refuses to run while a job is active.

-- OQ-26 item 5: Pendências show each date's latest processing. Issues of runs that published
-- nothing go, and so do issues of a date that a later published run covered for the issue's
-- chain (chainless issue types belong to the positions chain).
DELETE FROM processing.issues AS i
    USING processing.requests AS r
    WHERE i.request_id = r.id AND r.status NOT IN ('COMPLETED', 'COMPLETED_WITH_ISSUES');
DELETE FROM processing.issues AS i
    USING processing.requests AS mine
    WHERE i.request_id = mine.id
      AND EXISTS (SELECT 1 FROM processing.requests AS later
                  WHERE later.status IN ('COMPLETED', 'COMPLETED_WITH_ISSUES')
                    AND (later.scope = 'ALL' OR later.scope = COALESCE(i.chain, 'POSITIONS'))
                    AND i.affected_date BETWEEN later.requested_start_date AND later.requested_end_date
                    AND (later.created_at, later.id) > (mine.created_at, mine.id));

-- OQ-23 (1/4): date statuses, backfilled from what is published and the old markers.
CREATE TABLE processing.date_status (
    date DATE PRIMARY KEY,
    portfolio VARCHAR(32),
    cash VARCHAR(32),
    portfolio_previous VARCHAR(32),    -- the status before RUNNING, put back if the run ends without this date (OQ-26)
    cash_previous VARCHAR(32),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT date_status_portfolio_check CHECK (portfolio IS NULL OR portfolio IN ('FRESH','FRESH_WITH_ISSUES','STALE','RUNNING','FAILED')),
    CONSTRAINT date_status_cash_check CHECK (cash IS NULL OR cash IN ('FRESH','FRESH_WITH_ISSUES','STALE','RUNNING','FAILED')),
    CONSTRAINT date_status_portfolio_previous_check CHECK (portfolio_previous IS NULL OR (portfolio = 'RUNNING' AND portfolio_previous IN ('FRESH','FRESH_WITH_ISSUES','STALE','FAILED'))),
    CONSTRAINT date_status_cash_previous_check CHECK (cash_previous IS NULL OR (cash = 'RUNNING' AND cash_previous IN ('FRESH','FRESH_WITH_ISSUES','STALE','FAILED'))),
    CONSTRAINT date_status_not_empty CHECK (portfolio IS NOT NULL OR cash IS NOT NULL)
);
INSERT INTO processing.date_status (date, portfolio, cash)
SELECT d.date,
       CASE
           WHEN pm.metric_date IS NULL THEN NULL
           WHEN pm.metric_date >= LEAST(cs.positions_dirty_from, cs.valuation_dirty_from) THEN 'STALE'
           WHEN pm.valuation_status = 'MISSING' OR pm.pnl_status = 'MISSING'
                OR EXISTS (SELECT 1 FROM processing.issues AS i
                           WHERE i.issue_type = 'EXPIRED_OPEN_POSITION' AND i.affected_date = d.date)
               THEN 'FRESH_WITH_ISSUES'
           ELSE 'FRESH'
       END,
       CASE
           WHEN cb.balance_date IS NULL THEN NULL
           WHEN cb.balance_date >= cs.cash_dirty_from THEN 'STALE'
           ELSE 'FRESH'
       END
FROM (SELECT metric_date AS date FROM portfolio.portfolio_metrics
      UNION SELECT balance_date FROM portfolio.cash_balances) AS d
CROSS JOIN processing.calculation_state AS cs
LEFT JOIN portfolio.portfolio_metrics AS pm ON pm.metric_date = d.date
LEFT JOIN portfolio.cash_balances AS cb ON cb.balance_date = d.date;

-- OQ-23 (2/4): no markers, no revision counters.
ALTER TABLE processing.calculation_state
    DROP COLUMN trades_revision,
    DROP COLUMN cash_movements_revision,
    DROP COLUMN prices_revision,
    DROP COLUMN cash_dirty_from,
    DROP COLUMN positions_dirty_from,
    DROP COLUMN valuation_dirty_from;

-- OQ-23 (3/4): the request is the run. A SUPERSEDED request becomes FAILED, with its old status
-- kept as the error code. Runs that ended without publishing (staged publication published
-- nothing) lose their progress_date, which now means "last date committed".
UPDATE processing.requests
    SET status = 'FAILED', error_code = COALESCE(error_code, 'SUPERSEDED'),
        error_message = COALESCE(error_message,
            'Obsoleto: os dados de entrada mudaram durante o processamento e nada foi publicado.')
    WHERE status = 'SUPERSEDED';
UPDATE processing.requests SET progress_date = NULL WHERE status IN ('CANCELLED', 'FAILED');
ALTER TABLE processing.requests
    DROP CONSTRAINT requests_status_check,
    DROP CONSTRAINT requests_dates_ordered,
    DROP CONSTRAINT requests_effective_dates_ordered,
    DROP CONSTRAINT requests_progress_nonnegative,
    DROP COLUMN effective_start_date,
    DROP COLUMN effective_end_date,
    DROP COLUMN processed_days,
    DROP COLUMN total_days,
    DROP COLUMN trades_revision_at_start,
    DROP COLUMN cash_movements_revision_at_start,
    DROP COLUMN prices_revision_at_start,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE processing.requests
    SET updated_at = COALESCE(finished_at, started_at, dispatched_at, created_at);
ALTER TABLE processing.requests RENAME COLUMN requested_start_date TO start_date;
ALTER TABLE processing.requests RENAME COLUMN requested_end_date TO end_date;
UPDATE processing.requests SET progress_date = NULL
    WHERE progress_date IS NOT NULL AND progress_date NOT BETWEEN start_date AND end_date;
ALTER TABLE processing.requests
    ADD CONSTRAINT requests_dates_ordered CHECK (start_date <= end_date),
    ADD CONSTRAINT requests_status_check CHECK (status IN ('QUEUED','DISPATCHED','RUNNING','CANCELLING','COMPLETED','COMPLETED_WITH_ISSUES','CANCELLED','FAILED')),
    ADD CONSTRAINT requests_progress_in_range CHECK (progress_date IS NULL OR progress_date BETWEEN start_date AND end_date);

-- OQ-23 (4/4): no staging.
DROP TABLE portfolio.staged_position_metrics;
DROP TABLE portfolio.staged_positions;
DROP TABLE portfolio.staged_portfolio_metrics;
DROP TABLE portfolio.staged_cash_balances;

-- OQ-25: the published row records the source of the PU it used, instead of pointing at a
-- price row that can now be edited or deleted.
ALTER TABLE portfolio.position_metrics ADD COLUMN reference_source VARCHAR(16);
UPDATE portfolio.position_metrics AS pm SET reference_source = rp.source
    FROM prices.reference_prices AS rp WHERE rp.id = pm.reference_price_id;
ALTER TABLE portfolio.position_metrics DROP COLUMN reference_price_id;   -- drops its composite FK
ALTER TABLE portfolio.position_metrics
    ADD CONSTRAINT position_metrics_reference_source_check CHECK (reference_source IS NULL OR (reference_source IN ('MANUAL','B3') AND reference_pu IS NOT NULL));

-- OQ-25: one row per (asset, date, source). Superseded revisions are history that no longer exists.
DELETE FROM prices.reference_prices WHERE superseded_at IS NOT NULL;
DROP INDEX prices.reference_prices_revision_uq;
DROP INDEX prices.reference_prices_identity_date_uq;
DROP INDEX prices.reference_prices_current_uq;
DROP INDEX prices.reference_prices_date_active_idx;
ALTER TABLE prices.reference_prices
    DROP CONSTRAINT reference_prices_revision_positive,
    DROP CONSTRAINT reference_prices_superseded_after_creation,
    DROP COLUMN revision,
    DROP COLUMN superseded_at,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE prices.reference_prices SET updated_at = created_at;
ALTER TABLE prices.reference_prices
    ADD CONSTRAINT reference_prices_one_per_source UNIQUE (asset_id, reference_date, source);
CREATE INDEX reference_prices_date_idx ON prices.reference_prices (reference_date, asset_id);

-- OQ-24: one ledger entry table. Trades keep their id and seq; cash movements keep their id, get
-- 00:00 as their time and new seqs after every trade, in (date, created_at, id) order, and a signed
-- amount. Delete reasons and cash descriptions are not kept.
CREATE TABLE ledger.entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(8) NOT NULL,
    entry_date DATE NOT NULL,
    entry_time TIME NOT NULL,          -- Sao Paulo local time
    seq BIGINT GENERATED BY DEFAULT AS IDENTITY UNIQUE NOT NULL,
    asset_id UUID REFERENCES asset.instruments(id) ON DELETE RESTRICT,   -- TRADE only
    signed_quantity INTEGER,                                             -- TRADE only
    execution_pu NUMERIC,                                                -- TRADE only
    execution_rate NUMERIC,                                              -- TRADE only
    input_kind VARCHAR(8),                                               -- TRADE only
    cash_amount NUMERIC(20,2),         -- CASH only: positive = deposit (aporte), negative = withdrawal
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    deletion_batch_id UUID,            -- shared by the entries of one multi-delete
    CONSTRAINT entries_type_check CHECK (type IN ('TRADE','CASH')),
    CONSTRAINT entries_trade_shape CHECK (type <> 'TRADE' OR (
        asset_id IS NOT NULL AND signed_quantity IS NOT NULL AND signed_quantity <> 0
        AND execution_pu IS NOT NULL AND execution_pu > 0
        AND execution_rate IS NOT NULL AND execution_rate > -1
        AND input_kind IS NOT NULL AND input_kind IN ('PU','RATE') AND cash_amount IS NULL)),
    CONSTRAINT entries_cash_shape CHECK (type <> 'CASH' OR (
        cash_amount IS NOT NULL AND cash_amount <> 0
        AND asset_id IS NULL AND signed_quantity IS NULL AND execution_pu IS NULL
        AND execution_rate IS NULL AND input_kind IS NULL)),
    CONSTRAINT entries_deletion_batch_tied CHECK (deletion_batch_id IS NULL OR deleted_at IS NOT NULL)
);
CREATE INDEX entries_ordered_active_idx ON ledger.entries (entry_date, entry_time, seq) WHERE deleted_at IS NULL;
CREATE INDEX entries_asset_date_active_idx ON ledger.entries (asset_id, entry_date, seq) WHERE deleted_at IS NULL AND type = 'TRADE';
INSERT INTO ledger.entries (id, type, entry_date, entry_time, seq, asset_id, signed_quantity,
                            execution_pu, execution_rate, input_kind, created_at, deleted_at)
SELECT id, 'TRADE', trade_date, trade_time, seq, asset_id, signed_quantity, execution_pu,
       execution_rate, input_kind, created_at, deleted_at
FROM ledger.trades;
INSERT INTO ledger.entries (id, type, entry_date, entry_time, seq, cash_amount, created_at, deleted_at)
SELECT id, 'CASH', movement_date, TIME '00:00',
       (SELECT COALESCE(max(seq), 0) FROM ledger.trades)
           + row_number() OVER (ORDER BY movement_date, created_at, id),
       CASE movement_type WHEN 'DEPOSIT' THEN amount ELSE -amount END, created_at, deleted_at
FROM ledger.cash_movements;
SELECT setval(pg_get_serial_sequence('ledger.entries', 'seq'),
              COALESCE((SELECT max(seq) FROM ledger.entries), 0) + 1, false);
DROP TABLE ledger.trades;
DROP TABLE ledger.cash_movements;
