# Acceptance tests, phase 2 (spec §13, over HTTP and PostgreSQL)

The same proof as `tests/acceptance/` (phase 1, pure engines), now through the real app:
`create_app` on a fresh PostgreSQL 16 database migrated to head, with an injected clock
(OQ-14; spec §15 D4), driven only through `/api`. Only the catalogue roots (instrument type,
asset class) and B3 prices, which have no route, are inserted directly. Expected values come
from the docs: PUs and rates are spec §4.1's formulas evaluated in `support.py` with `decimal`.
Money, PUs and rates are compared as `Decimal` parsed from the JSON strings, never as text or
float. A scenario that processes asserts the run's status and `processing.date_status` before
its figures, so a failed setup run cannot pass silently.
These tests need `TEST_DATABASE_URL`; CI sets it and runs them.

| §13 case | Covered by |
|---|---|
| Challenge example (D2, D3, D4): PU, each entry's cash effect (summed by the test), reference price, rate recovered, not processed before a run | `test_challenge_example_http.py` |
| 1 PU ↔ rate, precision (12/10 places accepted, more refused), 1 day before maturity, maturity date (PU typed, rate 0), after maturity refused | `test_ledger_http.py`, `test_reference_prices_http.py` |
| 9 a write saves only the fact: no job, date status, issue, outbox message or published row (after a run: below) | `test_ledger_http.py`, `test_reference_prices_http.py` |
| 16 one ledger order `(date, time, seq)` across trades and cash; mixed batch hard delete, all or nothing, 404 | `test_ledger_http.py` |
| 17 MANUAL over B3, removing MANUAL lets B3 prevail, a later set replaces with a new id, exact date, no carry-forward | `test_reference_prices_http.py` |
| 17 (second half) a used price corrected then removed after a run: allowed, marks nothing, no job or pendência; the Carteira shows the current price beside the old figures, the date keeps its status, time and figures until the user reprocesses (worker run in-process, `run_worker`) | `test_price_change_after_a_run_http.py` |
| 22 page `limit` 0 and 201 refused, ledger entries and processing history | `test_ledger_http.py` |
| 23 Carteira summary, positions and P&L series after today refused | `test_challenge_example_http.py` |
| OQ-42 price reads after today accepted and empty | `test_reference_prices_http.py` |
| OQ-33 catalogue: codes upper-cased, accent-insensitive search, unknown `product_id` / `asset_class_id` → 422 | `test_catalogue_http.py` |

## Scenarios with a processing run

Each queues a request through `POST /api/processing/requests`, lets the one worker drain the
queue in-process with the real composition (`support.run_worker`: recover, then drain, OQ-45,
OQ-46), then reads `/api/portfolio/*` and `/api/processing/*` through `desk.Desk`. The API's
clock ticks one second per call within the fixed "today" (`support.TickingClock`), so requests
keep their FIFO order; each worker start has its own time, so processing times tell runs apart.
Every scenario asserts the run's status and `processing.date_status` before its figures.

| §13 case | Covered by |
|---|---|
| Challenge example end to end (D3): cash 109.090,91, DI1F28 1 @ 90.909,09, AUM 200.000 | `test_challenge_example_http.py` |
| 2, 3 increase, partial reduction keeps the averages, crossing zero (one ledger row), full close, time before seq, seq at the same time, assets independent | `test_positions_http.py` |
| 4, 5, 6 cash without P&L, P&L per asset then aggregated, cumulative, signed market value, AUM, movements change cash and AUM not P&L | `test_cash_and_pnl_http.py` |
| 13 CASH-only then POSITIONS-only and the reverse; AUM null until both chains are processed | `test_cash_and_pnl_http.py` |
| 7, 8 missing price: nulls, no carry-forward, weekend, D−1 missing, both missing, round trip, partial P&L never complete, `COMPLETED_WITH_ISSUES` | `test_missing_prices_http.py` |
| 15 day without expected asset, with and without the cash chain | `test_missing_prices_http.py` |
| 21 one pendência per (asset, required price date); one per asset for an expired position | `test_missing_prices_http.py`, `test_maturity_http.py` |
| 27 the 30-day P&L chart over not-processed, missing-price and failed days | `test_missing_prices_http.py` |
| Maturity (OQ-1): close on the date, PU 0 after, expired open position, no maturity-day price | `test_maturity_http.py` |
| 9, 16 (second halves) writes and a hard delete after a run change no processed status, time or figure | `test_processing_runs_http.py` |
| 10 overlapping requests in FIFO order, queued cancel, finished cancel 409, range after today 422 | `test_processing_runs_http.py` |
| 11 recovery at worker start: resume after `progress_date`; a cancel request ends `CANCELLED`, then the queue drains (the interrupted state is set in SQL) | `test_processing_runs_http.py` |
| 14, 18, 19 predecessor per chain, ALL with one or both chains failing, retry with the failed chain's scope, AUM null beside a failed chain | `test_processing_runs_http.py` |
| 17 (second half) | `test_price_change_after_a_run_http.py` |
| 20, 26 a gap after an earlier status, and an only-`FAILED` chain, are not the zero state | `test_processing_runs_http.py`, `test_missing_prices_http.py` |

Not reachable through the API, so covered in `tests/integration/processing/` and
`tests/integration/platform/test_processing_worker.py`: a technical error
inside one chain or outside every chain (cases 24, 25), a cancel during a run's last date and the
row-lock race between a queued cancel and the worker's take (case 10), `RUNNING` dates restored
from `*_previous` (case 11), and the RabbitMQ doorbell path itself.
