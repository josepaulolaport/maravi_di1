# Maravi DI1 Backoffice — Database schema specification

**Status:** Proposed target design, ready for SQLAlchemy 2.x/Alembic translation. The accompanying [`schema.sql`](schema.sql) is the full PostgreSQL 16+ DDL proposal. **Applied without errors to a fresh PostgreSQL 16 container on 2026-10-18 (19 tables created); the composite FK `position_metrics → reference_prices` was probed (a price of another date is rejected, a null price id accepted). No other constraint has been tested yet. Re-applied after the 2026-10-18 decisions (`trade_time NOT NULL`, staging in `portfolio`, `reference_pu >= 0`): applies, 19 tables; a trade without `trade_time` and a `reference_pu = 0` row were probed (rejected and accepted respectively). Re-applied after OQ-21 (cash and positions as separate chains), on 2026-10-18 at 21:30: applies, 21 tables; a request without `scope` or with an unknown scope, an `aum` without a market value and a negative `withdrawals` were rejected, a CASH request and a valid `cash_balances` row accepted. Re-applied after OQ-22 (`issues.chain`) at 21:40: applies, 21 tables. Alembic 0001 + 0002 build the same columns, constraints and indexes as this file (`tests/integration/test_cash_chain_migration.py`); the column order of a migrated database differs (PostgreSQL appends added columns), so nothing may rely on positional column order.**

## Settled scope

- Exactly **one portfolio**, so no `portfolio_id` or persistent `portfolio` business entity.
- Seven code modules: `asset`, `ledger`, `pricing`, `prices`, `portfolio`, `pnl`, `processing`. Database schemas only where tables exist; `pricing` and `pnl` are calculation-oriented.
- Calendar-day accounting and P&L processing; DI1 simplified **DC/365** calculation. No automatic weekend/holiday price carry-forward. Price lookup is **exact date**.
- `prices` owns reference observations from `MANUAL` and `B3`; `MANUAL` takes precedence, then `B3`. Each source retains its own active observation. Historical corrections append a new revision and supersede the prior row.
- `ledger` alone owns execution prices in immutable trade records. Prices do not flow from trades into reference prices.
- `portfolio.positions` stores signed quantities. `portfolio.position_metrics` stores open-position average entry PU/rate, referenced observation and PU, signed position market value (`financial_total`), and asset P&L components. `portfolio.portfolio_metrics` stores signed positions' total market value, AUM, portfolio P&L and completeness. `portfolio.cash_balances` stores the cash chain: each day's balance, trades cash flow, deposits and withdrawals (OQ-21).
- **AUM = cash_balances.cash_balance + portfolio_metrics.positions_market_value** for the same date, under the agreed simplified accounting model; no gross/net exposure fields and no duplicate `total_equity` column. Cash and positions are two separately processable chains (OQ-21).
- Only user-requested date-range processing enqueues work; input changes synchronously advance invalidation markers, **never automatically enqueue P&L calculations**.
- Multiple overlapping requests can be queued. Exactly one active `DISPATCHED`/`RUNNING`/`CANCELLING` job globally. Cancellation is cooperative and staged results are not published. Newer input revisions supersede stale jobs.
- PostgreSQL is the authoritative durable job queue. RabbitMQ transports work commands. `platform.outbox_messages` and `platform.inbox_messages` support at-least-once reliable delivery and consumer deduplication.

## Table inventory and primary keys

| Owner | Table | Primary key | Purpose |
|---|---|---|---|
| asset | `instrument_types` | `id` | FUTURE and future extensibility |
| asset | `asset_classes` | `id` | e.g. INTEREST_RATE_FUTURE, belongs to instrument type |
| asset | `products` | `id` | e.g. DI1; references asset class |
| asset | `futures` | `product_id` | shared futures face value, multiplier, settlement method |
| asset | `instruments` | `id` | dated/maturing contract, e.g. DI1F27 |
| ledger | `trades` | `id` | individually ordered signed trades, execution PU/rate, deletion audit |
| ledger | `cash_movements` | `id` | dated deposits/withdrawals, deletion audit |
| prices | `reference_prices` | `id` | append-on-correction, one active per `(asset, date, source)` |
| portfolio | `positions` | `(asset_id, position_date)` | daily closing position quantity |
| portfolio | `position_metrics` | `(asset_id, metric_date)` | daily asset accounting/valuation/P&L results |
| portfolio | `portfolio_metrics` | `metric_date` | daily market value, AUM and portfolio P&L |
| portfolio | `cash_balances` | `balance_date` | daily cash balance and its components (cash chain, OQ-21) |
| processing | `requests` | `id` | durable jobs with a scope (CASH, POSITIONS, ALL; OQ-21), cancellation/lease/progress |
| processing | `calculation_state` | constant `TRUE` | per-input revisions (trades, cash movements, prices), per-chain dirty marks (cash, positions, valuation), active request |
| processing | `issues` | `id` | job issues: `MISSING_REFERENCE_PRICE`, `EXPIRED_OPEN_POSITION`, `STALE_PREDECESSOR` (with its `chain`, CASH or POSITIONS, OQ-22) |
| portfolio | `staged_positions` | `(request_id, asset_id, position_date)` | unpublished calculation output (Portfolio owns staging, OQ-8) |
| portfolio | `staged_position_metrics` | `(request_id, asset_id, metric_date)` | unpublished asset metrics |
| portfolio | `staged_portfolio_metrics` | `(request_id, metric_date)` | unpublished aggregate metrics |
| portfolio | `staged_cash_balances` | `(request_id, balance_date)` | unpublished cash chain |
| platform | `outbox_messages` | `id` | committed commands awaiting broker publication |
| platform | `inbox_messages` | `(consumer_name, message_id)` | handler delivery deduplication |

## Important database integrity decisions

1. Cross-schema foreign keys **are allowed**. They protect persisted IDs but do not authorize writing another module's tables through another module's services.
2. Instrument/product codes are unique case-insensitively; instrument codes and trade values are validated.
3. Ledger soft deletion preserves original transaction economic fields, and repository methods must not permit economic modification. This is **not** DB-enforced immutability against privileged direct SQL writes.
4. `reference_prices` rows are immutable observations with `superseded_at`. There is one current revision per `(asset_id, reference_date, source)`. Active source selection is a domain/read rule (`MANUAL > B3`) and does not delete lower-priority source observations.
5. Published and staged `position_metrics.reference_price_id` have composite foreign keys ensuring that the chosen price observation matches **the same asset and exact calendar date**. This avoids joining today's price with yesterday's saved P&L.
6. The tables use PostgreSQL `NUMERIC` to preserve Python `Decimal` financial arithmetic. Precision (OQ-3): 34-digit context, `ROUND_HALF_UP`; calculated PU stored with 10 dp and calculated rate with 12 dp; typed values with more decimals are rejected; money stored exact and rounded to 2 dp only in the UI. Bounds are only the CHECKs below (OQ-14).
7. Missing valuation may yield `NULL` market value, daily P&L and AUM, **not zero**. Cash, quantities and average costs remain available. Zero closing quantity has zero closing market value, but same-day trades may still require a reference PU for Trades P&L.
8. `portfolio_metrics` carries both accounting-independent and price-dependent values; completeness is explicitly recorded via `valuation_status` and `pnl_status`.
9. Result publication must be atomic across the tables of the job's scope — `cash_balances` (CASH); `positions`, `position_metrics`, `portfolio_metrics` (POSITIONS); all four (ALL) — together with the `aum` recomputation, and protected by a final check of the scope's input revisions and the active worker claim token (OQ-21).
10. A cancellation stops work at a safe checkpoint, discards staging rows and leaves previously published results unchanged (but marked stale where relevant).

## Application invariants (not adequately expressible as ordinary CHECK constraints)

- The hierarchy must ensure that `asset.futures.product_id` points to a product whose class belongs to instrument type `FUTURE`; futures instruments require a maturity date. Enforce in Asset domain and integration tests. If untrusted direct DB writers are later allowed, add a DB trigger/denormalized composite FK strategy.
- A stored reference-rate and reference-PU pair must be mathematically consistent with its face value, maturity and the 365-day convention. Official source PU is authoritative; a calculated implied rate is derived metadata. Do not synthesize an official observation from a calculator preview.
- Each portfolio day's position is obtained by chronologically applying transactions, including closes and reversals. A reversing trade may close an old position and establish a new opposite position, without splitting the immutable ledger record.
- `position_metrics.daily_pnl = position_pnl + trades_pnl` if all inputs are complete. `portfolio_metrics.daily_pnl` is the sum of **all expected** asset daily P&L values, not just available rows. No capital deposits/withdrawals enter trading P&L.
- Cash movements affect cash; under the agreed simplified model, the trade cash effect is `-signed_quantity * execution_pu`. The cash chain reads only trades and cash movements; `cash_balances` rows chain day to day (OQ-21). The multiplier is stored but not applied (OQ-2). Daily P&L is never posted into cash.
- `ledger.trades`: `trade_time` is required, and same-date order is `(trade_date, trade_time, seq)` (OQ-13). Nothing is dated after today (São Paulo); trades and prices may be dated up to the maturity date inclusive, never after it; on the maturity date `execution_rate` is stored as 0 (OQ-1, OQ-14).
- After an instrument's maturity date its reference PU is 0 by definition: no `reference_prices` row exists or is accepted, and `position_metrics.reference_price_id` is NULL with `reference_pu = 0` (hence the CHECK `reference_pu >= 0`). An open position after maturity raises `EXPIRED_OPEN_POSITION` (OQ-1).
- A `positions` / `position_metrics` row exists for D exactly when the asset is expected on D: Q[D−1] ≠ 0 or a trade on D, including quantity 0 (OQ-10). `position_pnl` is 0 when Q[D−1] = 0 (OQ-4). The D−1 reference PU used is the one on D−1's `position_metrics` row (OQ-9).
- On a missing required reference PU, the worker produces a `processing.issues` record and incomplete results. `cumulative_pnl` remains unavailable from the first incomplete portfolio P&L day onward until the gap is resolved.
- A backdated trade marks cash **and** positions dirty from its date onward (`cash_dirty_from`, `positions_dirty_from`) and bumps `trades_revision`; a backdated cash movement marks only cash dirty and bumps `cash_movements_revision`. Reference-price corrections mark valuation/P&L dirty (`valuation_dirty_from`, `prices_revision`) without invalidating quantities or cash. No change enqueues processing (OQ-21).
- A job processes exactly [A, B] of its scope (OQ-11, OQ-21). Each chain checks its own A−1: positions stale or missing, or cash stale, still publish; those days read as stale (positions with `pnl_status = MISSING`) plus a `STALE_PREDECESSOR` issue whose `chain` names the chain. Cash never published at A−1 while an active entry is dated on or before A−1 refuses a CASH or ALL job when it starts: nothing is published and the request ends `FAILED` with `error_code = CASH_PREDECESSOR_MISSING` (OQ-22).
- Every processed day has a `portfolio_metrics` row, also with no expected asset: market value 0, position/trades/daily P&L 0, both statuses `COMPLETE`, `cumulative_pnl` carried from the previous day (`NULL` if already broken) (OQ-22). After a publish with the scope's revisions unchanged, a marker of that scope within [A, B] advances to B+1; one before A stays (OQ-12).
- `portfolio_metrics.aum` = `cash_balances.cash_balance` + `positions_market_value` for the same date, or `NULL` when either is missing. Whichever scope publishes recomputes `aum` for its days in the same transaction, reading the other chain's published value; one job runs at a time, so the two cannot race. An integration test checks the equality after CASH-only, POSITIONS-only and ALL publishes (OQ-21).
- A manual price supersedes B3 for that asset/day; when removing a manual observation, B3 becomes the active preferred source if present.
- A running job reads the source revisions of its scope when starting (CASH: trades + cash movements; POSITIONS: trades + prices; ALL: all three) and, before publication, checks them transactionally. If changed, results cannot publish as current (`SUPERSEDED`); the user may queue a replacement.
- To avoid job overlap, the dispatcher row-locks `processing.calculation_state` and sets `active_request_id`, transactionally changes `requests.status` to `DISPATCHED`, and creates a corresponding outbox message. Requests are dispatched in `(created_at, id)` order, excluding cancelled jobs. Worker leases and claim tokens fence crashed/duplicated worker executions. Worker ACK occurs after the corresponding persistent state is durably recorded.

## API and UI implications

- `GET /portfolio/positions?date=YYYY-MM-DD` returns one combined Portfolio read model from dated position/metrics/asset data. It must surface stale and incomplete states, and must not mix newly corrected reference prices with previously computed P&L.
- `GET /portfolio/summary?date=...` uses `portfolio_metrics` and `cash_balances`, with cash freshness reported separately from positions and valuation (OQ-21).
- `POST /processing/requests`, `GET /processing/requests`, `GET /processing/requests/{id}` and `POST /processing/requests/{id}/cancel` expose durable processing state.
- The `Cancel and Replace` UI operation (offered, OQ-20) can atomically request cancellation of an active job and queue a replacement (still no automatic job from input mutation).
- React/Mantine receives consolidated responses. PostgreSQL is responsible for efficient joins; application services and public interfaces remain separate for writes and calculations.

## Items intentionally not invented or silently finalized

- **Maturity settlement:** decided (OQ-1) — no automatic settlement; `settlement_method` and `settlement_description` are descriptive only.
- **Multiplier semantics:** decided (OQ-2) — stored, not applied now; a future calculator module will apply it.
- **Price input details:** `rate` can be nullable for official PU-only observations. Source-specific provider identifiers, raw data payloads, correction reasons and publication timestamps can be added when B3 ingestion is implemented.
- **Historical publication at larger scale:** this schema uses one transaction to publish a processed range. That is reasonable for the technical challenge; should workloads become extremely large, consider an atomic generation pointer without exposing snapshot IDs in user-facing APIs.
- **Downgrade:** `alembic downgrade 0001` reverts OQ-21; it refuses while published cash, published portfolio metrics, staged cash or a CASH/POSITIONS request exists, unless `-x allow_data_loss=true` is given. `alembic downgrade base` drops the six schemas and is meant for fresh or throwaway databases only. It refuses while trades, cash movements, reference prices, instruments or processing requests exist, unless `-x allow_data_loss=true` is given.
- **Physical DB verification:** the DDL applies on PostgreSQL 16 (see Status); it still needs Alembic migration generation and comprehensive constraint/integration tests before treating it as production-ready.
