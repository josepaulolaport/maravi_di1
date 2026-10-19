-- OQ-30: the reference PU, rate and source of a date live only in prices.reference_prices.
-- position_metrics keeps its computed financial_total and P&L; a price change marks the
-- positions chain stale from its date (OQ-23), so the copy is not needed to stay correct.
ALTER TABLE portfolio.position_metrics
    DROP CONSTRAINT position_metrics_reference_source_check,
    DROP CONSTRAINT position_metrics_reference_nonnegative,
    DROP COLUMN reference_source,
    DROP COLUMN reference_pu;
