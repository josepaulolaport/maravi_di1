"""SQL of the dispatcher and the worker over ``processing.requests``, ``calculation_state``,
``date_status`` and ``issues`` (OQ-5, OQ-23, OQ-26, OQ-40). Row locks are taken in a fixed
order: a run's row, then its dates ascending, then ``calculation_state`` (a run's end frees the
slot in its own transaction). The dispatcher takes ``calculation_state`` and reads the active run
without locking it, then locks only QUEUED runs, so no cycle forms."""

from __future__ import annotations

from sqlalchemy import TextClause, text

RUN_COLUMNS = (
    "id, scope, start_date, end_date, status, created_at, dispatched_at, started_at,"
    " finished_at, cancel_requested_at, progress_date, error_code, error_message, updated_at,"
    " failed_date, failed_chain"
)

LOCK_CALCULATION_STATE = text(
    "SELECT active_request_id FROM processing.calculation_state WHERE singleton FOR UPDATE"
)

SET_ACTIVE_REQUEST = text(
    "UPDATE processing.calculation_state SET active_request_id = :request_id,"
    " updated_at = :now WHERE singleton"
)

CLEAR_ACTIVE_REQUEST = text(
    "UPDATE processing.calculation_state SET active_request_id = NULL, updated_at = :now"
    " WHERE singleton AND active_request_id = :request_id"
)

LOCK_OLDEST_QUEUED = text(
    f"SELECT {RUN_COLUMNS} FROM processing.requests WHERE status = 'QUEUED'"
    " ORDER BY created_at, id LIMIT 1 FOR UPDATE"
)

LOCK_ACTIVE_RUNS = text(
    f"SELECT {RUN_COLUMNS} FROM processing.requests"
    " WHERE status IN ('DISPATCHED', 'RUNNING', 'CANCELLING') ORDER BY created_at, id FOR UPDATE"
)


def select_run(*, for_update: bool) -> TextClause:
    lock = " FOR UPDATE" if for_update else ""
    return text(f"SELECT {RUN_COLUMNS} FROM processing.requests WHERE id = :id{lock}")


UPDATE_RUN = text(
    "UPDATE processing.requests SET status = :status, dispatched_at = :dispatched_at,"
    " started_at = :started_at, finished_at = :finished_at,"
    " cancel_requested_at = :cancel_requested_at, progress_date = :progress_date,"
    " error_code = :error_code, error_message = :error_message, updated_at = :updated_at,"
    " failed_date = :failed_date, failed_chain = :failed_chain WHERE id = :id"
)

DATE_STATUS_COLUMNS = (
    "date, portfolio, cash, portfolio_previous, cash_previous, portfolio_processed_at,"
    " cash_processed_at"
)

LOCK_DATE_STATUSES = text(
    f"SELECT {DATE_STATUS_COLUMNS} FROM processing.date_status"
    " WHERE date BETWEEN :start_date AND :end_date ORDER BY date FOR UPDATE"
)

LOCK_RUNNING_DATES = text(
    f"SELECT {DATE_STATUS_COLUMNS} FROM processing.date_status"
    " WHERE date BETWEEN :start_date AND :end_date"
    " AND (portfolio = 'RUNNING' OR cash = 'RUNNING') ORDER BY date FOR UPDATE"
)

UPSERT_DATE_STATUS = text(
    f"INSERT INTO processing.date_status ({DATE_STATUS_COLUMNS}, updated_at)"
    " VALUES (:day, :portfolio, :cash, :portfolio_previous, :cash_previous,"
    " :portfolio_processed_at, :cash_processed_at, :now)"
    " ON CONFLICT (date) DO UPDATE SET portfolio = EXCLUDED.portfolio, cash = EXCLUDED.cash,"
    " portfolio_previous = EXCLUDED.portfolio_previous,"
    " cash_previous = EXCLUDED.cash_previous,"
    " portfolio_processed_at = EXCLUDED.portfolio_processed_at,"
    " cash_processed_at = EXCLUDED.cash_processed_at, updated_at = EXCLUDED.updated_at"
)

DELETE_DATE_STATUS = text("DELETE FROM processing.date_status WHERE date = :day")

DELETE_ISSUES_OF_DATE = text("DELETE FROM processing.issues WHERE affected_date = :day")

INSERT_ISSUE = text(
    "INSERT INTO processing.issues"
    " (request_id, asset_id, affected_date, required_price_date, issue_type, created_at)"
    " VALUES (:request_id, :asset_id, :affected_date, :required_price_date, :issue_type, :now)"
)
