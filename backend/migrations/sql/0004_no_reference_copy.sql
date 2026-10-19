-- OQ-30: the reference PU, rate and source of a date live only in prices.reference_prices.
-- position_metrics keeps its computed financial_total and P&L until the user processes the date
-- again (OQ-31); the screen shows the current price next to them, so no copy is kept.
ALTER TABLE portfolio.position_metrics
    DROP CONSTRAINT position_metrics_reference_source_check,
    DROP CONSTRAINT position_metrics_reference_nonnegative,
    DROP COLUMN reference_source,
    DROP COLUMN reference_pu;
