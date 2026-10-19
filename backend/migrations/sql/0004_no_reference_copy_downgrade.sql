-- Back to 0003: the columns come back empty (NULL); the copied PU and source are not rebuilt.
ALTER TABLE portfolio.position_metrics
    ADD COLUMN reference_pu NUMERIC,
    ADD COLUMN reference_source VARCHAR(16),
    ADD CONSTRAINT position_metrics_reference_nonnegative CHECK (reference_pu IS NULL OR reference_pu >= 0),
    ADD CONSTRAINT position_metrics_reference_source_check CHECK (reference_source IS NULL OR (reference_source IN ('MANUAL','B3') AND reference_pu IS NOT NULL));
