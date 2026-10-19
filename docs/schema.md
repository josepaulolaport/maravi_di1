# Maravi DI1 Backoffice — Database schema specification

**Status:** implemented. [`schema.sql`](schema.sql) is the complete PostgreSQL 16 schema (17 tables) and the result of Alembic revisions 0001 + 0002 + 0003 (head `0003`); `tests/integration/test_migrations_match_schema.py` checks that the revisions build the same columns, constraints and indexes, and `test_cash_chain_migration.py` and `test_one_status_per_date_migration.py` cover the CHECKs and keys added by 0002 (OQ-21, OQ-22) and 0003 (OQ-23, OQ-24, OQ-25). Last verified on 2026-10-19: upgrade to head on a fresh PostgreSQL 16 and the full backend suite pass. The column order of a migrated database differs from this file (PostgreSQL appends added columns), so nothing may rely on positional column order. A schema change needs a recorded decision and a new revision; released revisions are never edited.

## Settled scope

- Exactly **one portfolio**, so no `portfolio_id` or persistent `portfolio` business entity.
- Seven code modules: `asset`, `ledger`, `pricing`, `prices`, `portfolio`, `pnl`, `processing`. Database schemas only where tables exist; `pricing` and `pnl` are calculation-oriented.
- Calendar-day accounting and P&L processing; DI1 simplified **DC/365** calculation. No automatic weekend/holiday price carry-forward. Price lookup is **exact date**.
- `prices` owns reference observations from `MANUAL` and `B3`; `MANUAL` takes precedence, then `B3`. Each source has at most one observation per asset and date; a correction updates it in place and a removal deletes it (OQ-25).
- `ledger` alone owns execution prices, in immutable entries: one table, `ledger.entries`, holds trades and cash movements (OQ-24). Prices do not flow from trades into reference prices.
- `portfolio.positions` stores signed quantities. `portfolio.position_metrics` stores open-position average entry PU/rate, the reference PU used and its source (MANUAL or B3, OQ-25), signed position market value (`financial_total`), and asset P&L components. `portfolio.portfolio_metrics` stores signed positions' total market value, AUM, portfolio P&L and completeness. `portfolio.cash_balances` stores the cash chain: each day's balance, trades cash flow, deposits and withdrawals (OQ-21).
- **AUM = cash_balances.cash_balance + portfolio_metrics.positions_market_value** for the same date, under the agreed simplified accounting model; no gross/net exposure fields and no duplicate `total_equity` column. Cash and positions are two separately processable chains (OQ-21).
- Only user-requested date-range processing enqueues work; input changes synchronously mark the affected dates stale in `processing.date_status`, **never automatically enqueue P&L calculations** (OQ-23).
- Multiple overlapping requests can be queued. Exactly one active `DISPATCHED`/`RUNNING`/`CANCELLING` job globally. Cancellation is cooperative. A run publishes each date in its own transaction; there is no staging, no revision check and no `SUPERSEDED` (OQ-23).
- PostgreSQL is the authoritative durable job queue. RabbitMQ transports work commands. `platform.outbox_messages` and `platform.inbox_messages` support at-least-once reliable delivery and consumer deduplication.

## Table inventory and primary keys

| Owner | Table | Primary key | Purpose |
|---|---|---|---|
| asset | `instrument_types` | `id` | FUTURE and future extensibility |
| asset | `asset_classes` | `id` | e.g. INTEREST_RATE_FUTURE, belongs to instrument type |
| asset | `products` | `id` | e.g. DI1; references asset class |
| asset | `futures` | `product_id` | shared futures face value, multiplier, settlement method |
| asset | `instruments` | `id` | dated/maturing contract, e.g. DI1F27 |
| ledger | `entries` | `id` | trades and cash movements (`type` TRADE or CASH), ordered by `(entry_date, entry_time, seq)`, soft deletion with a batch id (OQ-24) |
| prices | `reference_prices` | `id` | one per `(asset, date, source)`, corrected in place, removed by deletion (OQ-25) |
| portfolio | `positions` | `(asset_id, position_date)` | daily closing position quantity |
| portfolio | `position_metrics` | `(asset_id, metric_date)` | daily asset accounting/valuation/P&L results |
| portfolio | `portfolio_metrics` | `metric_date` | daily market value, AUM and portfolio P&L |
| portfolio | `cash_balances` | `balance_date` | daily cash balance and its components (cash chain, OQ-21) |
| processing | `requests` | `id` | the runs: scope (OQ-21), range, status, last committed date, error, cancellation, lease (OQ-23) |
| processing | `calculation_state` | constant `TRUE` | the active request |
| processing | `date_status` | `date` | the current status of the portfolio and cash chains on each date; the single source of freshness (OQ-23) |
| processing | `issues` | `id` | job issues: `MISSING_REFERENCE_PRICE`, `EXPIRED_OPEN_POSITION`, `STALE_PREDECESSOR` (with its `chain`, CASH or POSITIONS, OQ-22) |
| platform | `outbox_messages` | `id` | committed commands awaiting broker publication |
| platform | `inbox_messages` | `(consumer_name, message_id)` | handler delivery deduplication |

## Important database integrity decisions

1. Cross-schema foreign keys **are allowed**. They protect persisted IDs but do not authorize writing another module's tables through another module's services.
2. Instrument/product codes are unique case-insensitively; instrument codes and trade values are validated.
3. Ledger soft deletion preserves original entry economic fields (a multi-delete shares a `deletion_batch_id`; there is no delete reason, OQ-24), and repository methods must not permit economic modification. This is **not** DB-enforced immutability against privileged direct SQL writes.
4. `reference_prices` has one row per `(asset_id, reference_date, source)`, without revisions: a correction updates it in place, a removal deletes it (OQ-25). Active source selection is a domain/read rule (`MANUAL > B3`) and does not delete lower-priority source observations.
5. `position_metrics` stores no reference price: the reference PU, rate and source of a date are read from `prices.reference_prices` (current preferred: MANUAL, else B3, exact date). A published day keeps its computed `financial_total` and P&L; a price change marks the positions chain stale from its date (OQ-23), so the screen shows the current price next to the last processed figures until the date is reprocessed (OQ-30).
6. The tables use PostgreSQL `NUMERIC` to preserve Python `Decimal` financial arithmetic. Precision (OQ-3): 34-digit context, `ROUND_HALF_UP`; calculated PU stored with 10 dp and calculated rate with 12 dp; typed values with more decimals are rejected; money stored exact and rounded to 2 dp only in the UI. Bounds are only the CHECKs below (OQ-14).
7. Missing valuation may yield `NULL` market value, daily P&L and AUM, **not zero**. Cash, quantities and average costs remain available. Zero closing quantity has zero closing market value, but same-day trades may still require a reference PU for Trades P&L.
8. `portfolio_metrics` carries both accounting-independent and price-dependent values; completeness is explicitly recorded via `valuation_status` and `pnl_status`.
9. Publication is per date (OQ-23): one transaction writes the date's rows of the run's scope — `cash_balances` (CASH); `positions`, `position_metrics`, `portfolio_metrics` (POSITIONS); all four (ALL) — recomputes the date's `aum`, sets the date's chain statuses in `date_status` and the run's `progress_date`, protected by the active worker claim token.
10. A cancellation is checked between dates: the current date commits and later dates are not touched. A failure at D rolls D back and marks D `FAILED` for the chain; later dates are not touched (OQ-23).

## Application invariants (not adequately expressible as ordinary CHECK constraints)

- The hierarchy must ensure that `asset.futures.product_id` points to a product whose class belongs to instrument type `FUTURE`; futures instruments require a maturity date. Enforce in Asset domain and integration tests. If untrusted direct DB writers are later allowed, add a DB trigger/denormalized composite FK strategy.
- A stored reference-rate and reference-PU pair must be mathematically consistent with its face value, maturity and the 365-day convention. Official source PU is authoritative; a calculated implied rate is derived metadata. Do not synthesize an official observation from a calculator preview.
- Each portfolio day's position is obtained by chronologically applying transactions, including closes and reversals. A reversing trade may close an old position and establish a new opposite position, without splitting the immutable ledger record.
- `position_metrics.daily_pnl = position_pnl + trades_pnl` if all inputs are complete. `portfolio_metrics.daily_pnl` is the sum of **all expected** asset daily P&L values, not just available rows. No capital deposits/withdrawals enter trading P&L.
- Cash movements affect cash; under the agreed simplified model, the trade cash effect is `-signed_quantity * execution_pu`. The cash chain reads only trades and cash movements; `cash_balances` rows chain day to day (OQ-21). The multiplier is stored but not applied (OQ-2). Daily P&L is never posted into cash.
- `ledger.entries`: `entry_time` is required for both types, and order is `(entry_date, entry_time, seq)` with one `seq` shared by trades and cash (OQ-13, OQ-24). A trade's cash effect is computed on read, never stored. Nothing is dated after today (São Paulo); trades and prices may be dated up to the maturity date inclusive, never after it; on the maturity date `execution_rate` is stored as 0 (OQ-1, OQ-14).
- After an instrument's maturity date its reference PU is 0 by definition: no `reference_prices` row exists or is accepted, and the read model shows `reference_pu = 0` with no source (OQ-30). An open position after maturity raises `EXPIRED_OPEN_POSITION` (OQ-1).
- A `positions` / `position_metrics` row exists for D exactly when the asset is expected on D: Q[D−1] ≠ 0 or a trade on D, including quantity 0 (OQ-10). `position_pnl` is 0 when Q[D−1] = 0 (OQ-4). The D−1 reference PU used is the one on D−1's `position_metrics` row (OQ-9).
- On a missing required reference PU, the worker produces a `processing.issues` record and incomplete results. `cumulative_pnl` remains unavailable from the first incomplete portfolio P&L day onward until the gap is resolved.
- A write dated W sets, in the same transaction, the affected chain to `STALE` in `processing.date_status` on every date ≥ W that has a status: a trade, both chains; a cash movement, `cash`; a reference price, `portfolio`. There are no dirty markers and no revision counters. No change enqueues processing (OQ-21, OQ-23).
- A job processes exactly [A, B] of its scope (OQ-11, OQ-21). Each chain checks its own A−1: positions stale or missing, or cash stale, still publish; those dates get the status `STALE` (positions with `pnl_status = MISSING`) plus a `STALE_PREDECESSOR` issue whose `chain` names the chain. A date is `FRESH` (or `FRESH_WITH_ISSUES`) only when the previous date is too, or is the zero state; the run reads the previous date's status under a row lock on `date_status`, so a concurrent write waits and then marks what it affects (OQ-23). Cash never published at A−1 while an active entry is dated on or before A−1 refuses a CASH or ALL job when it starts: nothing is published and the request ends `FAILED` with `error_code = CASH_PREDECESSOR_MISSING` (OQ-22).
- Every processed day has a `portfolio_metrics` row, also with no expected asset: market value 0, position/trades/daily P&L 0, both statuses `COMPLETE`, `cumulative_pnl` carried from the previous day (`NULL` if already broken) (OQ-22). 
- `portfolio_metrics.aum` = `cash_balances.cash_balance` + `positions_market_value` for the same date, or `NULL` when either is missing. Whichever scope publishes a date recomputes that date's `aum` in the same transaction, reading the other chain's published value; one job runs at a time, so the two cannot race. An integration test checks the equality after CASH-only, POSITIONS-only and ALL publishes (OQ-21).
- A manual price takes precedence over B3 for that asset/day; when the manual row is deleted, B3 becomes the preferred source if present (OQ-25).
- A run never stops for a concurrent write: the write marks the affected dates `STALE`, and a date the run computes later on top of a stale predecessor is `STALE` too. Recovery after a crash or lost lease resumes after `requests.progress_date` (OQ-23).
- To avoid job overlap, the dispatcher row-locks `processing.calculation_state` and sets `active_request_id`, transactionally changes `requests.status` to `DISPATCHED`, and creates a corresponding outbox message. Requests are dispatched in `(created_at, id)` order, excluding cancelled jobs. Worker leases and claim tokens fence crashed/duplicated worker executions. Worker ACK occurs after the corresponding persistent state is durably recorded.

## API and UI implications

- `GET /portfolio/positions?date=YYYY-MM-DD` returns one combined Portfolio read model from dated position/metrics/asset data. It must surface stale and incomplete states, and must not mix newly corrected reference prices with previously computed P&L.
- `GET /portfolio/summary?date=...` uses `portfolio_metrics` and `cash_balances`; the freshness of each chain comes from `processing.date_status` (OQ-21, OQ-23).
- `POST /processing/requests`, `GET /processing/requests`, `GET /processing/requests/{id}` and `POST /processing/requests/{id}/cancel` expose durable processing state.
- The `Cancel and Replace` UI operation (offered, OQ-20) can atomically request cancellation of an active job and queue a replacement (still no automatic job from input mutation).
- React/Mantine receives consolidated responses. PostgreSQL is responsible for efficient joins; application services and public interfaces remain separate for writes and calculations.

## Items intentionally not invented or silently finalized

- **Maturity settlement:** decided (OQ-1) — no automatic settlement; `settlement_method` and `settlement_description` are descriptive only.
- **Multiplier semantics:** decided (OQ-2) — stored, not applied now; a future calculator module will apply it.
- **Price input details:** `rate` can be nullable for official PU-only observations. Source-specific provider identifiers, raw data payloads, correction reasons and publication timestamps can be added when B3 ingestion is implemented.
- **Historical publication at larger scale:** one transaction per processed date (OQ-23).
- **Downgrade:** `alembic downgrade 0002` rebuilds the 0002 structure empty and carries nothing back (OQ-26 item 6); it always refuses while a job is active (`allow_data_loss` does not bypass that), and refuses while ledger entries, reference prices, requests, date statuses or published portfolio rows exist, unless `-x allow_data_loss=true` is given, and then it deletes those rows. `alembic downgrade 0001` reverts OQ-21; it refuses while a job is active, or while published cash, published portfolio metrics, any staged row, a CASH-chain issue or a CASH/POSITIONS request exists, unless `-x allow_data_loss=true` is given (offline `--sql` output skips these checks). `alembic downgrade base` drops the six schemas and is meant for fresh or throwaway databases only. It refuses while trades, cash movements, reference prices, instruments or processing requests exist, unless `-x allow_data_loss=true` is given.
- **Upgrade carry-over of 0003** (integrator choices, no real data exists yet): trades keep id and seq; cash movements keep their id, get `00:00`, new seqs after every trade and a signed amount; delete reasons and descriptions are not kept (OQ-24, OQ-26); only the current price revision stays, and published metrics keep the source of the PU they used; every published date gets its chain statuses from the old markers (`STALE` on or after the marker, `FRESH_WITH_ISSUES` for a `MISSING` valuation or P&L or an expired open position, otherwise `FRESH`); issues of runs that published nothing, and issues of a date that a later published run covered for the issue's chain (chainless issue types count as positions), are deleted (OQ-26 item 5); a `SUPERSEDED` request becomes `FAILED` with `error_code = 'SUPERSEDED'`, and old cancelled or failed runs, which published nothing, lose their `progress_date`.
- **Physical DB verification:** the DDL applies on PostgreSQL 16 (see Status); it still needs Alembic migration generation and comprehensive constraint/integration tests before treating it as production-ready.
