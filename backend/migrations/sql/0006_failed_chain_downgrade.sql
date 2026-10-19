-- Back to 0005: the run's first-failure columns go.
ALTER TABLE processing.requests
    DROP CONSTRAINT requests_failed_date_in_range,
    DROP CONSTRAINT requests_failed_chain_needs_date,
    DROP CONSTRAINT requests_failed_chain_check,
    DROP COLUMN failed_chain,
    DROP COLUMN failed_date;
