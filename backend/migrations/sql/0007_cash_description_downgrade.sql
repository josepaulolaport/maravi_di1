-- Back to 0006: the cash description goes, and with it every description entered.
ALTER TABLE ledger.entries
    DROP CONSTRAINT entries_description_cash_only,
    DROP COLUMN description;
