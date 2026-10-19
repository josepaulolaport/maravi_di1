-- OQ-40: a run records where it first failed. failed_chain is the chain that failed first
-- (CASH or POSITIONS); NULL with a failed_date is a failure that belongs to no chain (lease lost,
-- lock timeout, the AUM recompute), which fails the date for every chain and the run. Both stay
-- NULL for a run that never failed. "Solicitar novo processamento" on COMPLETED_WITH_ISSUES is
-- prefilled from them: that chain's scope, from failed_date to the run's end.
ALTER TABLE processing.requests
    ADD COLUMN failed_date DATE,
    ADD COLUMN failed_chain VARCHAR(16),
    ADD CONSTRAINT requests_failed_chain_check CHECK (failed_chain IS NULL OR failed_chain IN ('CASH','POSITIONS')),
    ADD CONSTRAINT requests_failed_chain_needs_date CHECK (failed_chain IS NULL OR failed_date IS NOT NULL),
    ADD CONSTRAINT requests_failed_date_in_range CHECK (failed_date IS NULL OR failed_date BETWEEN start_date AND end_date);
