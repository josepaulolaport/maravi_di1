# Acceptance tests, phase 2 (spec §13, over HTTP and PostgreSQL)

The same proof as `tests/acceptance/` (phase 1, pure engines), now through the real app:
`create_app` on a fresh PostgreSQL 16 database migrated to head, with an injected clock
(OQ-14; spec §15 D4), driven only through `/api`. Only the catalogue roots (instrument type,
asset class) and B3 prices, which have no route, are inserted directly. Expected values come
from the docs: PUs and rates are spec §4.1's formulas evaluated in `support.py` with `decimal`.
These tests need `TEST_DATABASE_URL`; CI sets it and runs them.

| §13 case | Covered by |
|---|---|
| Challenge example (D2, D3, D4): PU, each entry's cash effect (summed by the test), reference price, rate recovered, not processed before a run | `test_challenge_example_http.py` |
| 1 PU ↔ rate, precision (12/10 places accepted, more refused), 1 day before maturity, maturity date (PU typed, rate 0), after maturity refused | `test_ledger_http.py`, `test_reference_prices_http.py` |
| 9 (partial) a write saves only the fact: no job, date status, issue, outbox message or published row. "Processed dates unchanged" waits for a run | `test_ledger_http.py`, `test_reference_prices_http.py` |
| 16 (partial: "processed results unchanged" waits for a run) one ledger order `(date, time, seq)` across trades and cash; mixed batch hard delete, all or nothing, 404 | `test_ledger_http.py` |
| 17 MANUAL over B3, removing MANUAL lets B3 prevail, correction in place, exact date, no carry-forward | `test_reference_prices_http.py` |
| 22 page `limit` 0 and 201 refused, ledger entries and processing history | `test_ledger_http.py` |
| 23 Carteira summary, positions and P&L series after today refused | `test_challenge_example_http.py` |
| OQ-42 price reads after today accepted and empty | `test_reference_prices_http.py` |
| OQ-33 catalogue: codes upper-cased, accent-insensitive search, unknown `product_id` / `asset_class_id` → 422 | `test_catalogue_http.py` |

## Next: scenarios that need a processing run

Positions, P&L and AUM over HTTP (cases 2–8, 10–15, 18–21, 24–27) need the Wave 4 worker
(PR #78). There is no dispatcher (OQ-46): the worker recovers at its start, then drains the
queued requests (OQ-45/OQ-46). `PortfolioRangeProcessor` runs in-process against the same
database, so these tests will queue a run through `POST /api/processing/requests`, drain it in
the test, then read `/api/portfolio/*`. Planned first: the challenge
example end to end (cash 109.090,91, DI1F28 1 @ 90.909,09, AUM 200.000 on 01/01/2027), the
phase 1 two-asset scenario, a missing price giving a pendência and `COMPLETED_WITH_ISSUES`, the
predecessor rule, the P&L chart (OQ-41), and the second halves of cases 9 and 16: a write after a
run leaves every processed date's status, time and figures unchanged. The RabbitMQ path itself is the wiring's
end-to-end test, not these.
