# Maravi DI1 — Module-based parallel implementation plan

**Status:** implementation blueprint, 2026-10-18; implemented on `main`; progress and remaining work as of 2026-10-19 in §12. **Sources of truth:** `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, and the decisions confirmed in conversation (open ones in `docs/open-questions.md`). If these disagree, flag the discrepancy before implementation; do not silently alter domain rules.

## 0. Non-negotiable architecture

- Python 3.12+ / FastAPI / SQLAlchemy 2.x async / PostgreSQL 16+ / Alembic / `uv`. RabbitMQ via `aio-pika`. Docker Compose for API, PostgreSQL, RabbitMQ, the processing worker and the outbox relay; there is no dispatcher (OQ-46).
- React + TypeScript + **Mantine**, TanStack Query. Locked frontend toolchain (user, 2026-10-18): Vite, React with TypeScript (`strict`), React Router, Mantine (`core`, `hooks`, `form`, `dates` with dayjs, `notifications`, `charts`), Tabler icons, TanStack Query, MSW, Vitest with Testing Library and jsdom, ESLint (typescript-eslint, react-hooks) and Prettier; Node 24 LTS with npm. Each package is the current stable major published before 2026-10-04, pinned by `package-lock.json`. **All user-facing text in pt-BR**; identifiers/source files may be English. No auth. Exactly **one** portfolio, no `portfolio_id` anywhere.
- Modular monolith: `asset`, `pricing`, `ledger`, `prices`, `portfolio`, `pnl`, `processing`; shared technical infrastructure under `platform`. Each module has `public.py`, `application/services`, `application/interfaces` when it has several persistence ports (processing), `domain`, `infrastructure/` (persistence and any other outbound adapter), `presentation/http` and `presentation/messaging` (inbound adapters); create only used files/packages.
- Ownership: Asset owns product/instrument hierarchy and futures specs; Pricing owns **pure** DI1 PU/rate calculations; Ledger owns the immutable ledger entries in `ledger.entries`, trades with their execution values and cash movements (OQ-24); Prices owns manual/B3 reference prices, one per asset, date and source, without revisions (OQ-25); Portfolio owns dated `positions`, `position_metrics`, `portfolio_metrics`, `cash_balances` and frontend read query; PnL owns **pure** attribution and aggregation; Processing owns user-requested jobs, cancellation, preflight, the per-date chain status `processing.date_status` and per-date publication (OQ-23).
- No per-operation command classes, event-sourced rewrite, automatic P&L calculation, one RabbitMQ queue per module, separate Reader/Service class per operation or cross-module imports of private ORM/repositories. Service methods may combine reads and writes. Use narrow `Protocol` interfaces only where useful; dedicated `PortfolioService` is warranted for the published reads.
- Financial conventions: DI1 challenge rate ↔ PU uses actual calendar days / 365, face value 100,000 (product-configured); source selection MANUAL > B3 exact day only; no price carry-forward; daily calendar processing; zero initial cash/positions/P&L; chronological trades incl. reversals; no deposits/withdrawals in trading P&L. `financial_total = signed_quantity × reference_PU`, AUM = cash + sum signed market value. Positions store just quantity; asset and portfolio metrics in separate tables. Missing prices can leave accounting available but valuation/P&L incomplete.
- Input mutations only save the fact: nothing is marked stale and processing is never enqueued automatically; processed results stay as they are until the user processes again (OQ-31). Many overlapping queued requests permitted; only one active request; cancellation cooperative. The single worker (OQ-45) publishes each date in its own transaction and sets that date's chain status and processing time in `processing.date_status` (OQ-23, OQ-31); there is no staging. RabbitMQ carries only a doorbell message ("there is work"); the database owns status and order, and the single worker takes the oldest `QUEUED` request itself (OQ-46).
- Maturity, multiplier and precision are decided (OQ-1, OQ-2, OQ-3 in `docs/open-questions.md`): no automatic settlement (the user closes with a trade, up to the maturity date; value 0 after it); multiplier stored, not applied; 34-digit `Decimal`, `ROUND_HALF_UP`, PU 10 dp, rate 12 dp. Do not assume anything beyond them.

## 1. Target repository layout

```text
backend/
  pyproject.toml
  uv.lock
  alembic.ini
  migrations/
    env.py
    versions/                  # single owner / migration integrator
  src/di1/
    main.py
    composition/
      routers.py
      dependencies.py
      consumers.py
    platform/
      config.py
      database/
        base.py
        engine.py
        session.py
        unit_of_work.py
      messaging/
        connection.py
        publisher.py
        consumer.py
        envelope.py
        outbox.py
        inbox.py
        topology.py
      observability/
    shared/                    # frozen cross-module DTOs only if genuinely shared
    modules/
      asset/
      pricing/
      ledger/
      prices/
      portfolio/
      pnl/
      processing/
    workers/
      main.py
      outbox_relay.py
      healthcheck.py   # the Compose healthcheck of the worker and the relay
  tests/
    unit/
    integration/
    architecture/
    acceptance/      # spec §13 phase 1: pure Portfolio + PnL compositions, no I/O
frontend/
  src/
    features/
      assets/
      ledger/
      prices/
      portfolio/
      processing/
    api/
    shared/
compose.yaml
scripts/e2e.sh                 # make e2e: the challenge example on a throwaway Compose stack
```

Each active module normally implements `public.py`, `dependencies.py` if needed, `domain/`, `application/services/` (a 1:1 repository Protocol sits next to the services as `repository.py`), `application/interfaces/` when several ports (processing), `infrastructure/persistence/{models.py,repositories.py,queries/}`, `presentation/http/{router.py,schemas.py}`. `infrastructure/` holds `persistence/` and, when needed, other outbound adapters. Inbound RabbitMQ consumers and handlers live in the module's `presentation/messaging/` (initially only Processing has one); shared RabbitMQ infrastructure (connection, publisher, consumer base, envelope, outbox, inbox, topology) lives in `platform/messaging/`; business processing logic stays in `application/`. Domain code is deterministic and free of I/O and side effects: no filesystem, network, database, messaging, environment or system-clock access, while pure standard-library utilities (`datetime` arithmetic, `Decimal`, `Enum`, `dataclasses`) are allowed. Domain code does not log (logging belongs in the application, infrastructure or presentation layers) and communicates failures through exceptions and explicit results. It never generates randomness internally: a calculation that needs randomness (e.g. Monte Carlo) receives an explicit seed or an injected random-number generator, for reproducibility and testability. SQL queries belong in Infrastructure. FastAPI `Depends` belongs in HTTP adapters or dependency providers, **never** the application/domain or repositories. Worker constructors use plain Python factories, not FastAPI dependency injection.

## 2. Multi-agent operating model

**Worktree per implementation agent.** A shared **Architect/Integrator** is the only editor of shared composition files, initial Alembic migration, `pyproject.toml`, global API contracts and compose files; it reviews changes to the platform interfaces modules use (UoW, outbox writer), but `platform/**` belongs to lane H (OQ-17). Each module agent edits exclusively `modules/<module>/**` and `tests/unit/<module>/**`, plus agreed integration tests under a dedicated file namespace. The Frontend agent exclusively edits `frontend/**`. The Infrastructure agent edits `platform/**`, `workers/` bootstrap and root configuration in coordination with the integrator. No two agents edit the same file concurrently.

Recommended agents (a reviewer can be a second agent applied after each module PR):

| Lane | Ownership | Starts | Dependencies |
|---|---|---|---|
| A — Asset | `modules/asset/**`, `tests/unit/asset/**`, `tests/integration/asset/**` | Wave 1 | Frozen DTOs + schema |
| B — Pricing | `modules/pricing/**`, `tests/unit/pricing/**`, `tests/integration/pricing/**` | Wave 1 | Instrument contract; can use fixtures |
| C — Ledger | `modules/ledger/**`, `tests/unit/ledger/**` | Wave 2 | Asset & Pricing public interfaces |
| D — Prices | `modules/prices/**`, `tests/unit/prices/**` | Wave 2 | Asset & Pricing public interfaces |
| E — Portfolio | `modules/portfolio/**`, `tests/unit/portfolio/**` | Wave 1 pure accounting; Wave 3 DB/read | Ledger DTOs; PnL result DTOs; schemas |
| F — PnL | `modules/pnl/**`, `tests/unit/pnl/**` | Wave 1 | Position and Trade DTOs, fixed calculation formulas |
| G — Processing | `modules/processing/**`, `tests/unit/processing/**` | Wave 2 queue API; Wave 4 worker integration | All module public interfaces + platform messaging |
| H — Platform | `platform/**`, `workers/**` shared bootstrap | Wave 0 | Schema and doorbell/take contract (OQ-46) |
| I — Frontend | `frontend/**`, including the frontend build: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore` (its `web` service in `compose.yaml` is lane X's) | Wave 1 mock API | Drafts the HTTP response types and MSW fixtures from the spec and the Figma, as a contract proposal the integrator reconciles with the backend; backend not required |
| X — Integrator | `composition/**`, `main.py`, migrations, global tests (not `tests/acceptance/**` or `tests/integration/acceptance/**`, owned by the acceptance-tests session), shared contracts, CI, compose (`compose.yaml`, including the `web` and `seed` services), the end-to-end smoke (`scripts/e2e.sh`, `scripts/e2e_smoke.py`) and the catalogue seed (`scripts/seed_catalogue.sql`) | Throughout | Owns all cross-module wiring |

`tests/acceptance/**` (spec §13 acceptance tests, phase 1: pure Portfolio and PnL compositions, no I/O) and `tests/integration/acceptance/**` (phase 2: the same scenarios over HTTP and PostgreSQL) belong to the acceptance-tests session (user, 2026-10-19); it touches nothing else. Only phase 1 runs in the pre-commit hook; CI runs both, and so does `make test-backend` (the only run of phase 2 while GitHub Actions is down, CLAUDE.md §4).

If fewer agents: combine A+B, C+D, E+F; **do not** combine G with platform+integration until there are stable endpoints. A coding agent should not modify another lane's folder to make its tests pass: raise a contract change request to X. A lane's integration tests may import another lane's test seed read-only (lane B imports lane A's catalogue seed from `tests/integration/asset/conftest.py`; user, 2026-10-19); the owner changes that seed, and a change that breaks an importer goes through X.

### Worktree steps (example)

```bash
git worktree add ../maravi-asset -b feat/asset
git worktree add ../maravi-pricing -b feat/pricing
git worktree add ../maravi-ledger -b feat/ledger
git worktree add ../maravi-prices -b feat/prices
git worktree add ../maravi-portfolio -b feat/portfolio
git worktree add ../maravi-pnl -b feat/pnl
git worktree add ../maravi-processing -b feat/processing
```

Use a separate DB/schema namespace per worktree for integration testing, or a fresh per-test DB. Never point parallel agents at one shared mutable dev DB. PRs merge after unit tests, interface conformance, review and migration integration; do not let agents create competing Alembic revisions from the same parent.

## 3. Wave 0 — contract & foundation freeze (Integrator + Platform)

**Deliverables:**
- Verify supplied `schema.sql` against disposable PostgreSQL 16+; fix SQL defects before using it as migration baseline. Produce Alembic revision(s) **centrally**: one initial revision incorporating all table DDL, then one revision per recorded schema decision (0002: OQ-21/OQ-22; 0003: OQ-23/OQ-24/OQ-25), each running reviewed SQL from `migrations/sql/`. Validate downgrade only where safe and documented.
- Define stable public DTOs: `Instrument`, `LedgerEntry`, `ReferencePriceRecord`, `PositionState`, `AssetPnLResult`, `PortfolioPnLResult`, `CalculationCompleteness`, `ProcessingRequest`. Do not expose ORM types across modules.
- Freeze rate units (rate `0.135` = 13.5%) and deterministic UTC timestamp vs local business-date semantics. Freeze precision as decided in OQ-3 (34-digit `Decimal`, `ROUND_HALF_UP`, PU 10 dp, rate 12 dp, excess decimals rejected), and the same-day order `(entry_date, entry_time, seq)` across trades and cash movements, with `entry_time` required (OQ-13, OQ-24), and the error contract (OQ-15, `interfaces.md` "Errors").
- Define Unit of Work around one AsyncSession, SQLAlchemy database factory, API/worker bootstrap, error types, Pydantic API schemas, exceptions mapping.
- No invalidation contract (OQ-31): `FinancialResultInvalidator` (`trades_changed`, `cash_movements_changed`, `prices_changed`) is removed, and Ledger and Prices do not call Processing.
- Add baseline lint/type/test commands (ruff, pytest, optional mypy/pyright, migration smoke test). Set import boundary tests.
- Agree exact price input enum (`PU` or `RATE`) and source precedence; reference prices have no revisions: a later set of the same key deletes and inserts (new id), a removal deletes (OQ-25, OQ-26).

**Gate 0:** package imports and app starts, migration applies to fresh DB, cross-module contract examples compile, all agent lanes can branch from identical contract commit. Do not parallelize shared DTO design before this freeze.

## 4. Wave 1 — independent domain engines (parallel)

### A. Asset
- Implement `instrument_types`, `asset_classes`, `products`, `futures`, `instruments` models/repositories/validation and `AssetService`/`public.py`.
- Validate `FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27` hierarchy, product spec product-level, maturity instrument-level, case-insensitive unique codes, futures spec only for FUTURE product.
- Tests: invalid hierarchy, duplicate codes, missing maturity, futures spec lookup, contract DTO.
- **Done:** Asset public API can supply full DI1 descriptor for trade and pricing calculators.

### B. Pricing
- Pure DI1 calculator, signed Decimal inputs and exact DC/365 formula; inverse rate from PU; reference date/maturity validation and input-kind handling; explicit rounding rules once approved.
- Calculation response with PU, rate and input kind; no repositories, queues or PnL.
- Tests: challenge example, forward/inverse tolerance, leap-year/calendar-day count, zero remaining days, nonpositive PU, invalid rate, Decimal stability.
- **Done:** same calculator callable without FastAPI or DB.

### E. Portfolio (domain only)
- Pure chronological daily accounting engine using yesterday's state and day's sorted events; signed quantity, weighted-average PU/rate, partial close, flat and reversing trade. A separate pure cash chain (OQ-21): `cash[D] = cash[D−1] − Σ(q × PU_exec) + deposits − withdrawals`, from trades and cash movements only.
- Avg PU and rate are carried accounting inputs, even though persisted in `position_metrics`; cannot depend on market price presence.
- Tests: open/increase/partial-close/full-close/reversal/short, multiple same-day trades, backdated sequences, deposits/withdrawals; assert PnL never directly changes cash.
- **Done:** reconstructs accounting state for arbitrary fixture dates without infrastructure.

### F. PnL
- Pure per-asset `position_pnl = prior_quantity × (PU_today − PU_prior)` where required; `trades_pnl = Σ signed_trade_qty × (PU_today − execution_PU)`; aggregate only complete expected assets; cumulative chain invalid if previous day unavailable.
- Unit tests for long, short, same-day roundtrip, missing prior/current PU, zero positions, incomplete asset, incomplete chain; no cash-flows in PnL.
- **Done:** calculator returns explicit missing/completeness states and no persistence.

### I. Frontend (mock contracts)
- Implement existing pt-BR screens using Mantine and TanStack Query against typed MSW fixtures: Ativos, Lançamentos, Carteira, Central de Controle/Pendências/Processamentos. Since #114 MSW serves static fixtures to the tests only; development runs against the real API.
- Handle incomplete metric chips, the eight job statuses with their pt-BR labels (spec §10.3, OQ-20, OQ-23), the per-date Caixa and Posições statuses from `date_status` with "Processado em dd/mm/aaaa hh:mm" (spec §10.4, OQ-31), cancel and queue as separate actions (no cancel and replace, OQ-30), "Solicitar novo processamento" prefilled from the failed date or the first date not reached (OQ-23), exact-range preview and day progress. Design-vs-spec decisions: OQ-19, OQ-20.
- **Done:** screens demonstrated full flows on the fixtures before backend integration; Wave 5 moved them to the real API.

## 5. Wave 2 — input persistence + processing request API (parallel)

### C. Ledger
- `LedgerService` and repository over the one table `ledger.entries` (OQ-24): create entries (trade or cash movement), list them paginated, batch hard delete (OQ-32); deterministic order `(entry_date, entry_time, seq)` across both types; automatic PU/rate conversion via Pricing, product lookup via Asset.
- Only immutable economic fields, never edited; `delete_entries` is a real `DELETE` without a reason, all or nothing, and an unknown or already-deleted id answers 404 `NOT_FOUND` with nothing deleted; no audit trail, no `deleted_at` or `deletion_batch_id` (OQ-32). Each write only saves the fact in its UoW: no Processing call, no invalidation (OQ-31), no recalculation enqueue.
- Tests: multiple trades same date, trade and cash movement ordered by time and `seq`, mixed batch delete all or nothing, a batch with one unknown or already-deleted id deletes nothing (404), deleted entries absent from every read, execution price not added to `prices.reference_prices`.

### D. Prices
- `PriceService`: set a manual/B3 observation (a later set of the same key deletes the current row and inserts the new one), remove it (DELETE), preferred-by-source exact-date batch reads, unique per `(asset, date, source)` (OQ-25, OQ-26).
- Prefer MANUAL over B3; if removed, B3 becomes preferred. No silent older-date fallback. Price writes only save the price: nothing is marked (OQ-31).
- Tests: a second set of the same key gets a new id, removal lets B3 prevail, race/unique constraint, preferred-source priority, no carry-forward, absence of auto-processing.

### G. Processing (request API subset)
- `ProcessingService` enqueue/list/get/cancel with a scope (no cancel-and-replace, OQ-30) (CASH, POSITIONS, ALL; OQ-21), `processing.date_status` reads with the processing times (OQ-23, OQ-31), issue contract (two types, OQ-31).
- Support overlapping QUEUED ranges in PostgreSQL, one active global job invariant; queued cancel immediately, running cancel sets the cancellation marker, a finished job answers 409 (OQ-29; since OQ-46 no run is `DISPATCHED` or `CANCELLING`); a range ending after today is 422 `FUTURE_DATE` on request, cancel-and-replace and preview (OQ-29).
- Tests: concurrent enqueue, cancel then a separate new request.

### H. Platform (messaging subset)
- UoW, outbox write/relay with publisher confirms, inbox idempotency, aio-pika consumers, retry and failure policy, doorbell outbox message and the worker's SQL take of the oldest `QUEUED` request (one worker, so one active run; no lease or fencing, no dispatcher; OQ-45, OQ-46). Since OQ-50 item 2 (later PRs on `simplify`): the inbox, its retention, the dead-letter queues, the delivery limit, the redelivery backoff and the after-ack job queue are removed; the outbox carries one message per request.
- Tests: simulated relay crash and resend, duplicate delivery, ACK after durability, reconnect. Keep messaging adapters outside business services.

**Gate 2:** Create manual reference price and trade, read back independently, verify that no date status changed and **no** processing request was automatically created (OQ-31). Concurrent queued jobs can be inserted/cancelled.

## 6. Wave 3 — portfolio persistence and consolidated reads

**Portfolio lane E**, integrating with C, D, F and X:
- Persist `positions(asset_id, position_date, quantity)`, `position_metrics(asset_id, metric_date, avg PU/rate, financial_total, position/trades/daily PnL, status)`, `portfolio_metrics(metric_date, positions market value, AUM, portfolio PnL/status)`, `cash_balances(balance_date, cash_balance, trades_cash_flow, deposits, withdrawals)` (OQ-21). `position_metrics` stores no reference PU or source: the position table read takes each date's PU, rate and source from the current preferred price through `PriceReader` (OQ-30).
- `PortfolioService` returns one assembled frontend table; indexed read SQL in Portfolio Infrastructure only. Join published asset records and metrics by asset+date; include processing validity status. Show the current reference price (price table) next to the last processed figures, with each chain's status and processing time (OQ-30, OQ-31).
- `GET /portfolio/pnl` series (OQ-31 item 8): points are `date`, `daily_pnl`, `range_cumulative_pnl` and the positions chain's `status` (OQ-49); `range_cumulative_pnl` = Σ `daily_pnl` from the requested `start_date` to D, summed from the published rows on each request; since OQ-41 one point per calendar date of [`start_date`, `end_date`], and `range_cumulative_pnl` is never null: a date adds its `daily_pnl` only when its positions status is `PROCESSED` or `PROCESSED_WITH_ISSUES` and `daily_pnl` is not null, else 0 (OQ-41 item 4); an unprocessed point has `status` `NOT_PROCESSED` and `daily_pnl` null; a `FAILED` or `RUNNING` point has `daily_pnl` null; the stored since-inception `cumulative_pnl` stays on the summary and stays null from the first gap.
- Make read output distinguish `0`, `null` and each date's chain status from `processing.date_status` (not processed, `PROCESSED`, `PROCESSED_WITH_ISSUES`, `RUNNING`, `FAILED`) and its processing time per chain (OQ-23, OQ-31).
- Implement `PortfolioResultsWriter.write_positions_day` / `write_cash_day`, which upsert one date's published rows (AUM is computed on read by `PortfolioService`, OQ-21); Processing calls them through `public.py` inside each date's transaction (OQ-8, OQ-23). There is no staging. Since OQ-50 item 3 the position table marks a row whose current price of D or D−1 (integrator reading) has `created_at` after D's `portfolio_processed_at`.
- Tests: exact-day joins, null handling, average cost survives missing references, AUM computation, read consistency.

**Gate 3:** Portfolio table/summary available from seeded historical data with correct accounting and missing-price flags.

## 7. Wave 4 — processing worker + integration

**Processing lane G** with Platform lane H, Portfolio lane E, Integrator X:
- **No dispatcher (OQ-46, replacing OQ-45 item 5):** no dispatcher process, no Compose service, no dispatch tick, no slot. `enqueue_range` saves the request `QUEUED` and one doorbell outbox message (no request ID) in the same transaction. On every doorbell, and at worker start after recovery, the worker repeats until nothing is `QUEUED`: one transaction row-locks the oldest `QUEUED` request by `(created_at, id)` and sets it `RUNNING` with `started_at` (`PortfolioRangeProcessor.take_next()`, integrator choice); then it runs it. A doorbell that finds nothing does nothing; a lost one is recovered by any later doorbell or a restart; duplicates are harmless. One active run because one worker drains serially. `DISPATCHED`, `CANCELLING`, `requests.dispatched_at` and `calculation_state.active_request_id` stay in the schema unused, with no migration (integrator reading for `CANCELLING` and the slot). **Since OQ-50 (later PRs on `simplify`):** one message per request (its `request_id`); the id is for tracing only; on any message, and on a periodic sweep, the worker takes the oldest `QUEUED` request by `(created_at, id)`, FIFO unchanged (item 2). No date is written `RUNNING`; reads derive Processando from `progress_date + 1`, and `*_previous` is unused (item 4).
- `PortfolioRangeProcessor`: run by the single worker, with no claim token and no lease (OQ-45); process exactly the requested range and scope (OQ-11, OQ-21; days with no expected asset still get a `portfolio_metrics` row, OQ-22); a run may start on any date, and for each date D each chain checks that D−1 is `PROCESSED` or `PROCESSED_WITH_ISSUES` or the chain's zero state, otherwise D gets `FAILED` with `CASH_PREDECESSOR_MISSING` or `POSITIONS_PREDECESSOR_MISSING` ("Dia anterior não processado") and the run ends `FAILED`, later dates untouched (OQ-31); for ALL, when one chain fails on D (predecessor check or technical error), that chain gets `FAILED` on D and its later dates are untouched, the other chain is still written on D, in the same transaction, and continues to the end of the range (dates in order, one transaction per date, both chains in it while both are alive, no parallel execution), and the run ends `COMPLETED_WITH_ISSUES` with the first failure's `error_code`/`error_message`, or `FAILED` only when both chains fail (`POSITIONS_PREDECESSOR_MISSING` when both fail the predecessor check on the same date); on recovery, resuming after `progress_date`, a chain with a `FAILED` date in [`start_date`, `progress_date`] for this run stays stopped and only the other continues, read from `date_status` with nothing new stored; a cancel after one chain failed commits the current date and ends the run `CANCELLED`, keeping the first failure's `error_code`/`error_message` (OQ-36, replacing OQ-31 item 7); on ALL, D runs in one transaction with a SAVEPOINT per chain: a technical error rolls back only the failing chain to its savepoint and sets it `FAILED`, and the surviving chain's rows, AUM, `progress_date` and statuses commit in the same transaction; an error raised by a chain's writer call belongs to that chain; a non-chain failure (outside every chain's savepoint, e.g. a lock timeout on the date's status rows; integrator choice) rolls back all of D, D is `FAILED` for every chain still alive in the run and the run ends `FAILED`; a worker crash is not a failure at D (recovery at worker start, OQ-45); the run stores its first failure as `failed_date`/`failed_chain`; the zero state of a chain on D is no date before D with any status for the chain and no entry of its type on or before D−1, checked after OQ-37 item 4's `FAILED`/`RUNNING`/gap rules; a cancelled ALL run after a chain failed keeps `failed_date`/`failed_chain` (OQ-40 items 5 and 6); iterate **every calendar day**; order ledger events; for CASH call `CashCalculator`; for POSITIONS call `PositionsEngine`, preferred exact-day Prices for D and D−1 (the D−1 PU comes from the price table, OQ-30), `ValuationCalculator` and the PnL calculators; for ALL both, positions then cash, in the date's transaction (`run_chains.process_positions_day`, then `process_cash_day`). Per date (OQ-23): a short transaction sets the chain's status `RUNNING`; then one transaction locks the `date_status` rows of D−1 and D, writes D's published rows, sets D's status (`PROCESSED`, or `PROCESSED_WITH_ISSUES` with a missing price or an expired open position), the chain's `*_processed_at` and `requests.progress_date`, and commits (OQ-31). A run found at worker start with `cancel_requested_at` set has its `RUNNING` dates restored (flagged for the implementing PR, A1: since OQ-50 no date is written `RUNNING`, so nothing is restored) and ends `CANCELLED` before processing any date (user decision, OQ-45); there is no slot to free (OQ-46).
- On cancellation request, check between dates: the current date commits, later dates are not touched, the run ends `CANCELLED` (`COMPLETED`, or `COMPLETED_WITH_ISSUES` when a date it wrote has issues, if the cancel arrives during the last date; OQ-26); queued requests can be cancelled without broker work.
- On a chain failure at D, on every scope: roll the chain back to its SAVEPOINT inside D's transaction and, in that transaction, set it `FAILED` on D and store the run's `error_code`/`error_message` (`PROCESSING_ERROR`, "Erro técnico ao processar a data.", for a technical error, OQ-44); a single-chain run ends `FAILED`, later dates untouched (OQ-23; integrator choice). A non-chain failure, or an error that breaks the connection and cannot use a savepoint, rolls back all of D, and a short transaction sets D `FAILED` for every chain still alive with `failed_chain` NULL and ends the run `FAILED` (integrator choice). On ALL, D runs in one transaction with a SAVEPOINT per chain, a chain failure rolls back only that chain to its savepoint and sets it `FAILED` in D's transaction while the other chain commits (OQ-40), and the run ends `COMPLETED_WITH_ISSUES` when one chain fails, `FAILED` only when both fail (OQ-36).
- A write while running only saves its fact and marks nothing; the run never stops for it (no `SUPERSEDED`, OQ-31). On missing prices: preserve accounting, record `issues`, the date is `PROCESSED_WITH_ISSUES` with null dependent metrics and the run ends `COMPLETED_WITH_ISSUES`; do not retry domain-data gaps.
- Ack and recovery (integrator recording of lane G's reviewed Wave 4 plan, simplified by OQ-45 and OQ-46): exactly one `worker` service, handling one message at a time (prefetch 1); the doorbell carries no data, so the worker may ACK it on receipt (integrator reading), and a worker crash or SIGTERM gets no broker redelivery. Recovery happens only at worker start, before consuming: the run left `RUNNING` (the single such row) first has its `RUNNING` dates restored from `*_previous` (flagged for the implementing PR, A1: since OQ-50 no date is written `RUNNING`, so nothing is restored) (or the row deleted when there was no previous status, OQ-26; integrator reading), then resumes after `requests.progress_date`, or ends `CANCELLED` when `cancel_requested_at` is set (OQ-45); then the worker drains the `QUEUED` requests (OQ-46). A duplicate or redelivered doorbell is harmless: the take finds the next `QUEUED` request or nothing.
- No recovery cap (OQ-45 reverses OQ-43): `RECOVERY_EXHAUSTED` is retired; `requests.claim_token`, `lease_expires_at` and `attempt_count` stay in the schema unused (no migration). The worker code of #78 was simplified accordingly (#89; no dispatcher since #93/#96).
- **Test adversarial sequences:** queue A, create backdated trade, queue B, cancel A, finish B; duplicate and lost doorbells (a later doorbell or a restart drains the queue, OQ-46); cancel of a `QUEUED` request racing the take (one wins, OQ-46); crash after outbox publish; crash mid-date (resume after `progress_date` at worker start, `RUNNING` dates restored first (flagged for the implementing PR, A1: since OQ-50 no date is written `RUNNING`, so nothing is restored)); worker restart with a `RUNNING` run that has `cancel_requested_at` set (ends `CANCELLED`, then the queue drains); cancellation mid-range (committed dates stay published); a write landing during a date changes no status; failure at a date (earlier dates published, later untouched); missing Saturday price; a run whose first date has an unprocessed or `FAILED` D−1 (and entries before it) sets that date `FAILED` and ends `CASH_PREDECESSOR_MISSING` or `POSITIONS_PREDECESSOR_MISSING` (OQ-31); a D−1 price corrected after D−1 was processed leaves D−1 and D processed (OQ-9, OQ-31); both chains and the AUM of an ALL date in one transaction; a deposit during a POSITIONS job changes no status; `aum = cash + market value` after CASH-only, POSITIONS-only and ALL publishes; no half-written date.

**Gate 4:** Docker Compose e2e: new trade/price only saves the fact (OQ-31), user queues job, sees progress, cancels and queues a new request (OQ-30), published position table and AUM/PnL reflect the committed dates, each with its status and processing time from `date_status`.

## 8. Wave 5 — integration, hardening, reviewer checks

- Frontend I moved the screens to the typed API (#88); #114 then removed the MSW dev mode, so MSW only answers the tests with static fixtures. Integrator X owns cross-cutting API response compatibility. No secret changes to frontend requirements.
- Query index performance checks using `EXPLAIN (ANALYZE, BUFFERS)` on representative assets/dates; prefer one indexed Portfolio query over N+1 service calls.
- Include fixtures for weekends, missing prices, reversals and backdated corrections. Use deterministic clocks to test queue ordering.
- Tests: unit for calculators, integration on Postgres (not only SQLite), RabbitMQ e2e including retries, schema constraints, architecture import boundaries, frontend API contracts. `uv run pytest`, lint/type checks and Docker smoke instructions.
- Reviewer agent independently checks *financial math*, *transaction atomicity*, *race/cancellation/recovery*, *interface hygiene*, *migration quality*, *frontend pt-BR*. Reviews must point to failing tests or concrete violated contracts; implementer fixes then reviewer repeats until green.
- Document design rationale, nonrequirements, Docker local setup, demo script (the challenge example dated today, D4), the interpretations and deviations of spec §15, and the future CSV/B3 import TODO.

## 9. Integration and merge gates

- **G0** contract-freeze / initial migration / app boot.
- **G1** A+B+E(domain)+F unit tests green; no cross-module private imports.
- **G2** C+D+G(request)+H broker plumbing; writes save only the fact (OQ-31); no auto-recalc.
- **G3** Portfolio persistence/read models, dates+missing data correct.
- **G4** doorbell → worker take → per-date publication with `date_status`; cancel + overlapping requests, writes during a run, failure and recovery tested.
- **G5** frontend integrated, all e2e/constraints/documentation, Docker run reproducible.

Do not merge branches merely because code compiles. Require reviewer sign-off and tests. Use API/DTO contract tests to avoid coordination by shared ORM classes.

## 10. Agent handoff template (copy for each lane)

> You are the **[LANE]** implementation agent for Maravi DI1. Read `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, `docs/maravi_implementation_plan.md` and `docs/open-questions.md`. Own ONLY `[allowed directories]`. Implement Wave `[N]` deliverables for `[module]`. Preserve single-portfolio, exact-date prices (MANUAL > B3), DC/365, no automatic processing and no invalidation (OQ-31). Communicate only through frozen `public.py`/DTO contracts; no private cross-module imports; domain calculators pure; SQL in Infrastructure; `Depends` HTTP-only. Do not create/edit Alembic revisions or shared composition config: raise an integration request to X. Add focused unit tests and contract tests. Report changed files, commands/tests run, unresolved contract questions, deviations from spec, and edge cases. Stop if you discover ambiguity in settlement/multiplier rules; don't invent conventions.

**Reviewer prompt:** Independently compare the agent diff to its frozen interfaces, schema and acceptance tests. Search for invisible auto-recalculation, race conditions, results published twice from a duplicate message, missing worker-start recovery (OQ-45), duplicates, incorrect Decimal/365 math, incorrect sign on shorts, missing-price zero fallbacks, direct module-internal imports, and unauthorized edits outside the lane. Produce prioritized actionable findings; request correction and re-review.

## 11. Open decisions requiring human sign-off before relevant code

None. OQ-1 to OQ-47 are answered (`docs/open-questions.md`); a new gap goes through the `spec-gap` skill before any code depends on it.

**Post-completion TODO:** asynchronous CSV reference-price import and optional B3 extraction feeding `PriceService` via RabbitMQ adapter, not part of initial implementation.

## 12. Progress and remaining work (2026-10-19)

Every lane's code is merged. Decisions OQ-1 to OQ-48 are answered and none is open. OQ-47 records the user's answer to the pre-delivery code review ("all recommended"): robustness fixes, single-sourced rules, dead code removed and one frontend fix land in their own PRs; the rest is known debt, listed in the README ("Known limitations / technical debt").

### Verified on `main` at `bbf7027`

Run locally on 2026-10-19 on `bbf7027` (#108) plus this PR's docs-only commits (GitHub Actions is down; the user decided merges go on local results):

- `make lint`: ruff format "348 files already formatted"; mypy "Success: no issues found in 343 source files"; eslint and `tsc --noEmit` clean, "All matched files use Prettier code style!".
- `make test-backend` (throwaway PostgreSQL 16 and RabbitMQ 4.1): `alembic heads: 0006 (head)`, `alembic current after upgrade head: 0006 (head)`; "1366 passed in 252.88s", 0 skipped; coverage 99%.
- `make test-frontend`: "Test Files 33 passed (33)", "Tests 554 passed (554)". A first run in parallel with `make test-backend` and `make e2e` had 2 timeouts in `ProcessingTab.test.tsx`; the rerun alone passed.
- `make e2e` (throwaway Compose stack, its own project: postgres, rabbitmq, migrate, seed, api, demo, outbox-relay, worker, web): the challenge example dated today, 13 checks ok (PU 90909.0909090909, run `COMPLETED`, cash and positions `PROCESSED`, cash 109090.9090909091, AUM 200000, one position of quantity 1), "E2E SMOKE PASSED", and the `web` service serves the UI and forwards the API.

### Done, by area

| Area | On `main` (merged PRs) |
|---|---|
| Docs and decisions | spec, schema, interfaces, plan and challenge audit (#1–#3, #8); OQ-19/OQ-20 (#12); OQ-21/OQ-22 (#36); OQ-23–OQ-26 (#43); OQ-27 (#40); OQ-28 (#46); OQ-29–OQ-31 (#49); OQ-32–OQ-40 (#54); OQ-41 (#59); OQ-42 (#68); OQ-43/OQ-44 (#82); OQ-45 (#85, reverses OQ-43); OQ-46 (#91); commit freely, review at PR time (#67); plan §12 and status lines (#98); process docs (#102); 4-decimal rate display (#107); OQ-47, the code-review decisions (this PR) |
| Schema | Alembic 0001 to 0006, head `0006` = `docs/schema.sql`, equivalence-tested (#6, #36, #43, #50, #53, #58) |
| Backend scaffold and shared | scaffold and import-boundary tests (#4, #5); decimals and clock (#7); error catalogue and problem+json (#26) |
| Platform (H) | config, clock, async database, Unit of Work (#23); messaging: envelope, outbox, inbox, publisher, relay, consumer (#31); logging and relay process (#57); worker processes (#74) and startup recovery hook (#89); publish test fix (#80) |
| Composition (X) | public contracts (#37, #49); app factory, `/health` (#45); routes under `/api` (#61, #62, #77); backend image, Compose and API logging (#75); worker and relay wired to Processing and run in Compose (#92); `make e2e` and README demo (#86); RabbitMQ in CI (#69); DI1 catalogue seeded on every `docker compose up` by the one-shot `seed` service, ledger timestamps in UTC (#102); two weeks of demo history loaded on `up` by the one-shot `demo` service through the HTTP API, `scripts/seed_demo.py` (#104); `make e2e` safe in several worktrees at once, project from `DI1_E2E_PROJECT` (#106, #108) |
| A Asset | catalogue, `AssetReader`, HTTP (#47) |
| B Pricing | DI1 calculator (#24); `PricingService` over `AssetReader` (#52) |
| C Ledger | `ledger.entries`, batch hard delete, keyset list, HTTP (#48, #63) |
| D Prices | reference prices, `PriceReader`, `/reference-prices` (#65, #76) |
| E Portfolio | positions, cash and valuation chains (#28); source tracing (#44); writer, queries and P&L series with every date (#73) |
| F PnL | pure P&L calculators (#34); predecessor rule after OQ-31 (#70) |
| G Processing | request API and `DateStatusReader` (#56); worker, one transaction per date (#78); first failure exposed (#79); OQ-46 doorbell and FIFO drain, no dispatcher (#93, #96, #97) |
| Acceptance (spec §13) | phase 1, domain level, in the pre-commit hook (#64, #66); phase 2 over HTTP and PostgreSQL: catalogue, ledger, prices, errors, the challenge example (#81); follow-ups: case 17, setup checks, Decimal (#100); the §13 scenarios end to end with the worker: the challenge example through a run, queue, recovery, predecessor rule, maturity (#101); `failed_chain` when both chains fail on one date (#103) |
| I Frontend | shell, Carteira, Lançamentos, Ativos, Central de Controle on MSW (#13, #15, #16, #19, #20, #22, #25, #27, #29, #30, #32, #33); contract review and OQ-26–OQ-42 (#38, #41, #42, #51, #72); no dispatcher and `PROCESSING_ERROR` (#95); dev-server proxy to the real backend, `VITE_API_MOCKS=false` (#88); `web` service in Compose, nginx on 127.0.0.1:8080 proxying `/api` and `/health`, no MSW in the production build (#99); post-QA fixes: 404 on deletion, KPI layout, future dates refused out loud, queued vs running cancel copy, rates with 4 decimals, Definir preço period (#105) |
| CI | path-scoped jobs, `ci-ok`, CodeRabbit review (#9–#11, #21) |

Gates: G0–G5 are met (Gate 4 by `make e2e` on Compose: challenge example, run `COMPLETED`, cash, AUM and position checked; G5 by #99: the UI runs on the real API from the Compose `web` service).

### Remaining

| Item | State |
|---|---|
| Code-review follow-ups (OQ-47): robustness fixes (inbox retention among them), single-sourced rules, dead code, one frontend fix | in flight, in their own PRs |
| Lane I UI decisions (OQ-48): `Instrument.last_reference` filled through `prices.public.PriceReader.latest` (Asset HTTP joins it; composition wires the reader); price entry from the Ativos product page and the Carteira "P&L acumulado" headline (lane I, frontend only) | contract in `prices/public.py`; done |
| Known technical debt (OQ-47 item 5) | deferred by the user; listed in the README, "Known limitations / technical debt" |
| `POST /pricing/calculate` | deliberately not built: OQ-19 keeps it "if needed", and the backend computes the complementary PU or rate when an entry is saved (OQ-19 item 7) |
| CSV and B3 reference-price import | post-delivery TODO (§11, spec §14) |
