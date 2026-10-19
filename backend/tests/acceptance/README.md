# Acceptance tests (spec §13)

Proof that the build matches the challenge and the specification. Expected values are computed
by hand from the spec formulas, in each test's docstring, never by running the code under test.

## Phase 1: domain level (this folder, no database)

By convention, imports go only through `portfolio.public` and `pnl.public`. The architecture
tests scan `src/` only, so they do not enforce this here.

`harness.py` composes the pure engines one calendar day at a time, as a processed day does:
positions and cash chains (`portfolio.public`), valuation, per-asset P&L and aggregation
(`pnl.public`). It stands in for Prices and Processing in two rules: the exact-date reference
PU with no carry-forward (§5), and PU 0 after maturity in P&L (§7.4, OQ-1). The engines keep no
price history, so phase 1 proves that a missing price gives null (never 0) and that a PU of 0
is used when given. That the real pipeline never carries a price forward and passes 0 after
maturity is a phase 2 obligation.

| §13 case | Covered by |
|---|---|
| Maturity (OQ-1): close on the date, PU 0 after | `test_maturity.py` |
| 2 intraday order, reversal | `test_positions_and_order.py` |
| 3 average PU and rate, partial close, full close | `test_positions_and_order.py` |
| 4 cash without P&L | `test_cash_and_pnl.py` |
| 5 position, trades, daily, aggregation, cumulative | `test_cash_and_pnl.py` |
| 6 movements change cash and AUM, not P&L | `test_cash_and_pnl.py` |
| 7 null on a missing exact-date price, weekend, flat, round trip | `test_missing_prices_and_calendar.py` |
| 8 partial P&L never complete | `test_missing_prices_and_calendar.py` |
| 15 day without expected asset (P&L 0, AUM = cash) | `test_missing_prices_and_calendar.py` |
| Challenge example (D2, D4) | `test_challenge_example.py` |

Partly here: case 13 and OQ-38 (AUM null without a cash balance: valuation only).

## Phase 2: over HTTP (not built yet)

Same scenarios against the wired API, PostgreSQL and the Wave 4 worker, with the clock injected
at 01/01/2027 (D4): register the contracts, entries and prices through the API, request
processing, wait for the job, read `/portfolio/*`. It adds what the domain cannot reach:
PU ↔ rate and pricing at maturity (1), no carry-forward and PU 0 after maturity in the real
pipeline (7, OQ-1), MANUAL over B3 (17), no invalidation (9), queue and cancellation (10),
per-date publication and the predecessor rule (11, 14, 20, 24–26), the consolidated read (12),
chains and AUM (13, 18, 19), ledger order across trades and cash and hard delete (16), pendências
(21), limits and future dates (22, 23) and the P&L chart (27, OQ-41).
