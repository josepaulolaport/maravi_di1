# Maravi DI1 — Module-based parallel implementation plan

**Status:** implementation blueprint, 2026-10-18; progress and remaining work as of 2026-10-19 in §12. **Sources of truth:** `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, and the decisions confirmed in conversation (open ones in `docs/open-questions.md`). If these disagree, flag the discrepancy before implementation; do not silently alter domain rules.

## 0. Non-negotiable architecture

- Python 3.12+ / FastAPI / SQLAlchemy 2.x async / PostgreSQL 16+ / Alembic / `uv`. RabbitMQ via `aio-pika`. Docker Compose for API, PostgreSQL, RabbitMQ, processing worker, dispatcher and outbox relay (roles can share a worker process for local simplicity if semantics remain intact).
- React + TypeScript + **Mantine**, TanStack Query. Locked frontend toolchain (user, 2026-10-18): Vite, React with TypeScript (`strict`), React Router, Mantine (`core`, `hooks`, `form`, `dates` with dayjs, `notifications`, `charts`), Tabler icons, TanStack Query, MSW, Vitest with Testing Library and jsdom, ESLint (typescript-eslint, react-hooks) and Prettier; Node 24 LTS with npm. Each package is the current stable major published before 2026-10-04, pinned by `package-lock.json`. **All user-facing text in pt-BR**; identifiers/source files may be English. No auth. Exactly **one** portfolio, no `portfolio_id` anywhere.
- Modular monolith: `asset`, `pricing`, `ledger`, `prices`, `portfolio`, `pnl`, `processing`; shared technical infrastructure under `platform`. Each module has `public.py`, `application/services`, `application/interfaces` where useful, `domain`, `infrastructure/` (persistence and any other outbound adapter), `presentation/http` and `presentation/messaging` (inbound adapters); create only used files/packages.
- Ownership: Asset owns product/instrument hierarchy and futures specs; Pricing owns **pure** DI1 PU/rate calculations; Ledger owns the immutable ledger entries in `ledger.entries`, trades with their execution values and cash movements (OQ-24); Prices owns manual/B3 reference prices, one per asset, date and source, without revisions (OQ-25); Portfolio owns dated `positions`, `position_metrics`, `portfolio_metrics`, `cash_balances` and frontend read query; PnL owns **pure** attribution and aggregation; Processing owns user-requested jobs, cancellation, preflight, the per-date chain status `processing.date_status` and per-date publication (OQ-23).
- No per-operation command classes, event-sourced rewrite, automatic P&L calculation, one RabbitMQ queue per module, separate Reader/Service class per operation or cross-module imports of private ORM/repositories. Service methods may combine reads and writes. Use narrow `Protocol` interfaces only where useful; dedicated `PortfolioQueryService` is warranted.
- Financial conventions: DI1 challenge rate ↔ PU uses actual calendar days / 365, face value 100,000 (product-configured); source selection MANUAL > B3 exact day only; no price carry-forward; daily calendar processing; zero initial cash/positions/P&L; chronological trades incl. reversals; no deposits/withdrawals in trading P&L. `financial_total = signed_quantity × reference_PU`, AUM = cash + sum signed market value. Positions store just quantity; asset and portfolio metrics in separate tables. Missing prices can leave accounting available but valuation/P&L incomplete.
- Input mutations only save the fact: nothing is marked stale and processing is never enqueued automatically; processed results stay as they are until the user processes again (OQ-31). Many overlapping queued requests permitted; only one active request; cancellation cooperative. Worker publishes each date in its own transaction while its claim token is valid, and sets that date's chain status and processing time in `processing.date_status` (OQ-23, OQ-31); there is no staging. RabbitMQ dispatches work, database owns status/order.
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
      dispatcher.py
      outbox_relay.py
  tests/
    unit/
    integration/
    architecture/
    e2e/
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
```

Each active module normally implements `public.py`, `dependencies.py` if needed, `domain/`, `application/services/`, `application/interfaces/` when meaningful, `infrastructure/persistence/{models.py,repositories.py,queries/}`, `presentation/http/{router.py,schemas.py}`. `infrastructure/` holds `persistence/` and, when needed, other outbound adapters. Inbound RabbitMQ consumers and handlers live in the module's `presentation/messaging/` (initially only Processing has one); shared RabbitMQ infrastructure (connection, publisher, consumer base, envelope, outbox, inbox, topology) lives in `platform/messaging/`; business processing logic stays in `application/`. Domain code is deterministic and free of I/O and side effects: no filesystem, network, database, messaging, environment or system-clock access, while pure standard-library utilities (`datetime` arithmetic, `Decimal`, `Enum`, `dataclasses`) are allowed. Domain code does not log (logging belongs in the application, infrastructure or presentation layers) and communicates failures through exceptions and explicit results. It never generates randomness internally: a calculation that needs randomness (e.g. Monte Carlo) receives an explicit seed or an injected random-number generator, for reproducibility and testability. SQL queries belong in Infrastructure. FastAPI `Depends` belongs in HTTP adapters or dependency providers, **never** the application/domain or repositories. Worker constructors use plain Python factories, not FastAPI dependency injection.

## 2. Multi-agent operating model

**Worktree per implementation agent.** A shared **Architect/Integrator** is the only editor of shared composition files, initial Alembic migration, `pyproject.toml`, global API contracts and compose files; it reviews changes to the platform interfaces modules use (UoW, outbox writer), but `platform/**` belongs to lane H (OQ-17). Each module agent edits exclusively `modules/<module>/**` and `tests/unit/<module>/**`, plus agreed integration tests under a dedicated file namespace. The Frontend agent exclusively edits `frontend/**`. The Infrastructure agent edits `platform/**`, `workers/` bootstrap and root configuration in coordination with the integrator. No two agents edit the same file concurrently.

Recommended agents (a reviewer can be a second agent applied after each module PR):

| Lane | Ownership | Starts | Dependencies |
|---|---|---|---|
| A — Asset | `modules/asset/**`, `tests/unit/asset/**`, `tests/integration/asset/**` | Wave 1 | Frozen DTOs + schema |
| B — Pricing | `modules/pricing/**`, `tests/unit/pricing/**`, `tests/integration/pricing/**` | Wave 1 | InstrumentDescriptor contract; can use fixtures |
| C — Ledger | `modules/ledger/**`, `tests/unit/ledger/**` | Wave 2 | Asset & Pricing public interfaces |
| D — Prices | `modules/prices/**`, `tests/unit/prices/**` | Wave 2 | Asset & Pricing public interfaces |
| E — Portfolio | `modules/portfolio/**`, `tests/unit/portfolio/**` | Wave 1 pure accounting; Wave 3 DB/read | Ledger DTOs; PnL result DTOs; schemas |
| F — PnL | `modules/pnl/**`, `tests/unit/pnl/**` | Wave 1 | Position and Trade DTOs, fixed calculation formulas |
| G — Processing | `modules/processing/**`, `tests/unit/processing/**` | Wave 2 queue API; Wave 4 worker integration | All module public interfaces + platform messaging |
| H — Platform | `platform/**`, `workers/**` shared bootstrap | Wave 0 | Schema and dispatch contract |
| I — Frontend | `frontend/**` | Wave 1 mock API | Drafts the HTTP response types and MSW fixtures from the spec and the Figma, as a contract proposal the integrator reconciles with the backend; backend not required |
| X — Integrator | `composition/**`, `main.py`, migrations, global tests, shared contracts, CI, compose | Throughout | Owns all cross-module wiring |

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
- Define stable public DTOs: `InstrumentDescriptor`, `TradeRecord`, `CashMovementRecord`, `ReferencePriceRecord`, `PositionState`, `AssetPnLResult`, `PortfolioPnLResult`, `CalculationCompleteness`, `ProcessingRequest`. Do not expose ORM types across modules.
- Freeze rate units (rate `0.135` = 13.5%) and deterministic UTC timestamp vs local business-date semantics. Freeze precision as decided in OQ-3 (34-digit `Decimal`, `ROUND_HALF_UP`, PU 10 dp, rate 12 dp, excess decimals rejected), and the same-day order `(entry_date, entry_time, seq)` across trades and cash movements, with `entry_time` required (OQ-13, OQ-24), and the error contract (OQ-15, `interfaces.md` "Errors").
- Define Unit of Work around one AsyncSession, SQLAlchemy database factory, API/worker bootstrap, error types, Pydantic API schemas, exceptions mapping.
- No invalidation contract (OQ-31): `FinancialResultInvalidator` (`trades_changed`, `cash_movements_changed`, `prices_changed`) is removed, and Ledger and Prices do not call Processing.
- Add baseline lint/type/test commands (ruff, pytest, optional mypy/pyright, migration smoke test). Set import boundary tests.
- Agree exact price input enum (`PU` or `RATE`) and source precedence; reference prices have no revisions: a correction updates in place, a removal deletes (OQ-25).

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
- Implement existing pt-BR screens using Mantine and TanStack Query against typed mock API fixtures: Ativos, Lançamentos, Carteira, Central de Controle/Pendências/Processamentos.
- Handle incomplete metric chips, the eight job statuses with their pt-BR labels (spec §10.3, OQ-20, OQ-23), the per-date Caixa and Posições statuses from `date_status` with "Processado em dd/mm/aaaa hh:mm" (spec §10.4, OQ-31), cancel and queue as separate actions (no cancel and replace, OQ-30), "Solicitar novo processamento" prefilled from the failed date or the first date not reached (OQ-23), exact-range preview and day progress. Design-vs-spec decisions: OQ-19, OQ-20.
- **Done:** screens demonstrate full flows with mock adapters before backend integration.

## 5. Wave 2 — input persistence + processing request API (parallel)

### C. Ledger
- `LedgerService` and repository over the one table `ledger.entries` (OQ-24): create entries (trade or cash movement), list them paginated, batch hard delete (OQ-32); deterministic order `(entry_date, entry_time, seq)` across both types; automatic PU/rate conversion via Pricing, product lookup via Asset.
- Only immutable economic fields, never edited; `delete_entries` is a real `DELETE` without a reason, all or nothing, and an unknown or already-deleted id answers 404 `NOT_FOUND` with nothing deleted; no audit trail, no `deleted_at` or `deletion_batch_id` (OQ-32). Each write only saves the fact in its UoW: no Processing call, no invalidation (OQ-31), no recalculation enqueue.
- Tests: multiple trades same date, trade and cash movement ordered by time and `seq`, mixed batch delete all or nothing, a batch with one unknown or already-deleted id deletes nothing (404), deleted entries absent from every read, execution price not added to `prices.reference_prices`.

### D. Prices
- `PriceService`: set a manual/B3 observation, correct it in place, remove it (DELETE), preferred-by-source exact-date batch reads, unique per `(asset, date, source)` (OQ-25).
- Prefer MANUAL over B3; if removed, B3 becomes preferred. No silent older-date fallback. Price writes only save the price: nothing is marked (OQ-31).
- Tests: correction keeps the id, removal lets B3 prevail, race/unique constraint, preferred-source priority, no carry-forward, absence of auto-processing.

### G. Processing (request API subset)
- `ProcessingService` enqueue/list/get/cancel with a scope (no cancel-and-replace, OQ-30) (CASH, POSITIONS, ALL; OQ-21), `processing.date_status` reads with the processing times (OQ-23, OQ-31), issue contract (two types, OQ-31).
- Support overlapping QUEUED ranges in PostgreSQL, one active global job invariant; queued cancel immediately, dispatched cancel moves to `CANCELLING` (the worker ends it `CANCELLED` on claim), running cancel sets the cancellation marker, a `CANCELLING` or finished job answers 409 (OQ-29); a range ending after today is 422 `FUTURE_DATE` on request, cancel-and-replace and preview (OQ-29).
- Tests: concurrent enqueue, cancel then a separate new request.

### H. Platform (messaging subset)
- UoW, outbox write/relay with publisher confirms, inbox idempotency, aio-pika consumers, retry and failure policy, SQL-controlled dispatch leases/fencing.
- Tests: simulated relay crash and resend, duplicate delivery, ACK after durability, reconnect. Keep messaging adapters outside business services.

**Gate 2:** Create manual reference price and trade, read back independently, verify that no date status changed and **no** processing request was automatically created (OQ-31). Concurrent queued jobs can be inserted/cancelled.

## 6. Wave 3 — portfolio persistence and consolidated reads

**Portfolio lane E**, integrating with C, D, F and X:
- Persist `positions(asset_id, position_date, quantity)`, `position_metrics(asset_id, metric_date, avg PU/rate, financial_total, position/trades/daily PnL, status)`, `portfolio_metrics(metric_date, positions market value, AUM, portfolio PnL/status)`, `cash_balances(balance_date, cash_balance, trades_cash_flow, deposits, withdrawals)` (OQ-21). `position_metrics` stores no reference PU or source: the position table read takes each date's PU, rate and source from the current preferred price through `PriceReader` (OQ-30).
- `PortfolioQueryService` returns one assembled frontend table; indexed read SQL in Portfolio Infrastructure only. Join published asset records and metrics by asset+date; include processing validity status. Show the current reference price (price table) next to the last processed figures, with each chain's status and processing time (OQ-30, OQ-31).
- `GET /portfolio/pnl` series (OQ-31 item 8): points carry only the positions chain's status and processing time (`published_at`), plus `range_cumulative_pnl` = Σ `daily_pnl` from the requested `start_date` to D, summed from the published rows on each request, `null` from the first date with a null `daily_pnl` or no published positions day; `cumulative_pnl` (since inception) stays in the point.
- Make read output distinguish `0`, `null` and each date's chain status from `processing.date_status` (not processed, `PROCESSED`, `PROCESSED_WITH_ISSUES`, `RUNNING`, `FAILED`) and its processing time per chain (OQ-23, OQ-31).
- Implement `PortfolioResultsWriter.write_positions_day` / `write_cash_day`, which upsert one date's published rows and its AUM; Processing calls them through `public.py` inside each date's transaction (OQ-8, OQ-23). There is no staging.
- Tests: exact-day joins, null handling, average cost survives missing references, AUM computation, read consistency.

**Gate 3:** Portfolio table/summary available from seeded historical data with correct accounting and missing-price flags.

## 7. Wave 4 — processing worker + integration

**Processing lane G** with Platform lane H, Portfolio lane E, Integrator X:
- `ProcessingDispatcher`: lock singleton calculation state; select oldest eligible queued job; set `DISPATCHED` and outbox command atomically. One active global job (even if broker duplicates messages).
- `PortfolioRangeProcessor`: worker claim token + lease; process exactly the requested range and scope (OQ-11, OQ-21; days with no expected asset still get a `portfolio_metrics` row, OQ-22); a run may start on any date, and for each date D each chain checks that D−1 is `PROCESSED` or `PROCESSED_WITH_ISSUES` or the chain's zero state, otherwise D gets `FAILED` with `CASH_PREDECESSOR_MISSING` or `POSITIONS_PREDECESSOR_MISSING` ("Dia anterior não processado") and the run ends `FAILED`, later dates untouched (OQ-31); for ALL, when one chain fails on D (predecessor check or technical error), that chain gets `FAILED` on D and its later dates are untouched, the other chain is still written on D, in the same transaction, and continues to the end of the range (dates in order, one transaction per date, both chains in it while both are alive, no parallel execution), and the run ends `COMPLETED_WITH_ISSUES` with the first failure's `error_code`/`error_message`, or `FAILED` only when both chains fail (`POSITIONS_PREDECESSOR_MISSING` when both fail the predecessor check on the same date); on recovery, resuming after `progress_date`, a chain with a `FAILED` date in [`start_date`, `progress_date`] for this run stays stopped and only the other continues, read from `date_status` with nothing new stored; a cancel after one chain failed commits the current date and ends the run `CANCELLED`, keeping the first failure's `error_code`/`error_message` (OQ-36, replacing OQ-31 item 7); iterate **every calendar day**; order ledger events; for CASH call `CashCalculator`; for POSITIONS call `PositionsEngine`, preferred exact-day Prices for D and D−1 (the D−1 PU comes from the price table, OQ-30), `ValuationCalculator` and the PnL calculators; for ALL both (`PortfolioAccounting` runs the two chains together). Per date (OQ-23): a short transaction sets the chain's status `RUNNING`; then one transaction locks the `date_status` rows of D−1 and D, writes D's published rows and AUM, sets D's status (`PROCESSED`, or `PROCESSED_WITH_ISSUES` with a missing price or an expired open position), the chain's `*_processed_at` and `requests.progress_date`, and commits (OQ-31).
- On cancellation request, check between dates: the current date commits, later dates are not touched, the run ends `CANCELLED` (`COMPLETED`, or `COMPLETED_WITH_ISSUES` when a date it wrote has issues, if the cancel arrives during the last date; OQ-26); queued requests can be cancelled without broker work.
- In each date's transaction verify the claim token. On failure at D: roll back D, set D `FAILED` and the run's `error_code`/`error_message` in a short transaction, end `FAILED`, leave later dates untouched (OQ-23).
- A write while running only saves its fact and marks nothing; the run never stops for it (no `SUPERSEDED`, OQ-31). On missing prices: preserve accounting, record `issues`, the date is `PROCESSED_WITH_ISSUES` with null dependent metrics and the run ends `COMPLETED_WITH_ISSUES`; do not retry domain-data gaps.
- On process death: lease expiry/recovery resumes after `requests.progress_date`; idempotent dispatch/inbox and fencing; no concurrent global workers even if multiple processes.
- **Test adversarial sequences:** queue A, create backdated trade, queue B, cancel A, finish B; duplicate deliveries; crash after outbox publish; crash mid-date (resume after `progress_date`); cancellation mid-range (committed dates stay published); a write landing during a date changes no status; failure at a date (earlier dates published, later untouched); missing Saturday price; a run whose first date has an unprocessed or `FAILED` D−1 (and entries before it) sets that date `FAILED` and ends `CASH_PREDECESSOR_MISSING` or `POSITIONS_PREDECESSOR_MISSING` (OQ-31); a D−1 price corrected after D−1 was processed leaves D−1 and D processed (OQ-9, OQ-31); both chains and the AUM of an ALL date in one transaction; a deposit during a POSITIONS job changes no status; `aum = cash + market value` after CASH-only, POSITIONS-only and ALL publishes; no half-written date.

**Gate 4:** Docker Compose e2e: new trade/price only saves the fact (OQ-31), user queues job, sees progress, cancels and queues a new request (OQ-30), published position table and AUM/PnL reflect the committed dates, each with its status and processing time from `date_status`.

## 8. Wave 5 — integration, hardening, reviewer checks

- Frontend I swaps mock adapters for typed APIs; Integrator X owns cross-cutting API response compatibility. No secret changes to frontend requirements.
- Query index performance checks using `EXPLAIN (ANALYZE, BUFFERS)` on representative assets/dates; prefer one indexed Portfolio query over N+1 service calls.
- Include fixtures for weekends, missing prices, reversals and backdated corrections. Use deterministic clocks to test queue ordering/lease expiry.
- Tests: unit for calculators, integration on Postgres (not only SQLite), RabbitMQ e2e including retries, schema constraints, architecture import boundaries, frontend API contracts. `uv run pytest`, lint/type checks and Docker smoke instructions.
- Reviewer agent independently checks *financial math*, *transaction atomicity*, *race/cancellation/recovery*, *interface hygiene*, *migration quality*, *frontend pt-BR*. Reviews must point to failing tests or concrete violated contracts; implementer fixes then reviewer repeats until green.
- Document design rationale, nonrequirements, Docker local setup, demo script (the challenge example dated today, D4), the interpretations and deviations of spec §15, and the future CSV/B3 import TODO.

## 9. Integration and merge gates

- **G0** contract-freeze / initial migration / app boot.
- **G1** A+B+E(domain)+F unit tests green; no cross-module private imports.
- **G2** C+D+G(request)+H broker plumbing; writes save only the fact (OQ-31); no auto-recalc.
- **G3** Portfolio persistence/read models, dates+missing data correct.
- **G4** dispatch → worker → per-date publication with `date_status`; cancel + overlapping requests, writes during a run, failure and recovery tested.
- **G5** frontend integrated, all e2e/constraints/documentation, Docker run reproducible.

Do not merge branches merely because code compiles. Require reviewer sign-off and tests. Use API/DTO contract tests to avoid coordination by shared ORM classes.

## 10. Agent handoff template (copy for each lane)

> You are the **[LANE]** implementation agent for Maravi DI1. Read `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, `docs/maravi_implementation_plan.md` and `docs/open-questions.md`. Own ONLY `[allowed directories]`. Implement Wave `[N]` deliverables for `[module]`. Preserve single-portfolio, exact-date prices (MANUAL > B3), DC/365, no automatic processing and no invalidation (OQ-31). Communicate only through frozen `public.py`/DTO contracts; no private cross-module imports; domain calculators pure; SQL in Infrastructure; `Depends` HTTP-only. Do not create/edit Alembic revisions or shared composition config: raise an integration request to X. Add focused unit tests and contract tests. Report changed files, commands/tests run, unresolved contract questions, deviations from spec, and edge cases. Stop if you discover ambiguity in settlement/multiplier rules; don't invent conventions.

**Reviewer prompt:** Independently compare the agent diff to its frozen interfaces, schema and acceptance tests. Search for invisible auto-recalculation, race conditions, results published by a fenced-out worker, duplicates, incorrect Decimal/365 math, incorrect sign on shorts, missing-price zero fallbacks, direct module-internal imports, and unauthorized edits outside the lane. Produce prioritized actionable findings; request correction and re-review.

## 11. Open decisions requiring human sign-off before relevant code

None. OQ-1 to OQ-31 are answered (`docs/open-questions.md`); a new gap goes through the `spec-gap` skill before any code depends on it.

**Post-completion TODO:** asynchronous CSV reference-price import and optional B3 extraction feeding `PriceService` via RabbitMQ adapter, not part of initial implementation.

## 12. Progress and remaining work (2026-10-19)

Verified on `main` at `81cbbb7`: `make lint-backend` clean; `make test-backend` 513 passed with PostgreSQL 16 and RabbitMQ 4.1 (0 skipped), migrations at head `0003`; frontend lint, typecheck, Prettier, 468 tests and `vite build` pass.

### Done

| Area | On `main` |
|---|---|
| Docs | OQ-1 to OQ-28 answered: cash and positions chains (OQ-21, OQ-22), per-date status with no staging (OQ-23), one ledger entry (OQ-24), prices without revisions (OQ-25), follow-ups and HTTP contract (OQ-26), chart start date (OQ-27), AUM without status (OQ-28) |
| Schema | Alembic 0001 + 0002 + 0003 = `docs/schema.sql`, equivalence-tested |
| Shared | decimals (OQ-3), clock, calendar, error catalogue (OQ-15), `InputKind` |
| Platform (H) | config, system clock, async engine/session, Unit of Work; messaging: envelope, outbox, relay with confirms, inbox, publisher, consumer, topology |
| Composition (X) | app factory `main.py`, `/health`, problem+json handlers, empty router and dependency wiring |
| Contracts (`public.py`) | asset, ledger, prices, processing (invalidator, scope, statuses, request); fake invalidator in `tests/fakes/processing.py` (the invalidator and its fake are removed by OQ-31) |
| Domain | pricing DI1 calculator (B); portfolio positions, average cost, cash, valuation, accounting (E); P&L position, trades, asset, portfolio (F), one file per metric |
| CI | path-scoped backend and frontend jobs, `ci-ok`, CodeRabbit review |
| Frontend (I) | Carteira, Lançamentos, Ativos, Central de Controle on MSW, against the OQ-26 contract |

Gates: G0 met except Compose; G1 waits on lane A (Asset).

### Remaining, by lane

| Lane | Next work | Depends on |
|---|---|---|
| X | `pricing/public.py`, `portfolio/public.py` (`PortfolioResultsWriter`, `PortfolioQueryService`), `pnl/public.py`; RabbitMQ service in CI (`TEST_RABBITMQ_URL`, `TEST_RABBITMQ_MANAGEMENT_URL`, `REQUIRE_BROKER_TESTS=1`); Compose with PostgreSQL, RabbitMQ, a migrate job and the api, plus the Dockerfile (workers later); wire each lane's router in `composition/`; README demo with the challenge example dated today (D4) | — |
| A Asset | models and repository over `asset.*`, `AssetService`, `AssetReader` implementation, HTTP (`/instrument-types`, `/products`, `/instruments`) | — |
| B Pricing | `PricingService.calculate(instrument_id, reference_date, quote)` over the calculator, reading the instrument through `AssetReader` | `pricing/public.py` |
| C Ledger | `ledger.entries` persistence, `LedgerService` create and batch hard delete (OQ-32), `LedgerReader.get_trades`/`get_cash_movements`, `EntryType` and `LedgerReader.has_entries_on_or_before` for the zero-state check (OQ-37), no invalidation (OQ-31), HTTP `/ledger/entries` (paginated) and `/ledger/entries/deletions` | asset and pricing public contracts (fakes until they land) |
| D Prices | one observation per asset, date and source; `PriceService` set, correct in place, remove; `PriceReader` exact-date preferred reads (MANUAL > B3); no invalidation (OQ-31); HTTP | asset and pricing public contracts |
| G Processing | request API: preview, enqueue, paginated history, cancel (no cancel-and-replace, OQ-30), `processing.date_status` reads with the processing times (no invalidator, OQ-31), issues. Then Wave 4: dispatcher, claim and lease, one transaction per date with the per-day predecessor rule (OQ-31), `RUNNING` restore, recovery from `progress_date` | request API: none; worker: E's writer, H's workers |
| E Portfolio | Wave 3: `PortfolioResultsWriter.write_positions_day`/`write_cash_day` with the AUM recomputation, `PortfolioQueryService` (summary, positions, P&L series), mapping `ledger.public.TradeRecord` onto the domain trade | `portfolio/public.py` |
| F PnL | free: spec §13 acceptance fixtures across portfolio and P&L, or pair with G on the worker | — |
| H Platform | H3 logging and `workers/outbox_relay.py` bootstrap; worker entry points for G; Compose infra with X | — |
| I Frontend | mark `frontend/src/api/README.md` as the adopted contract (OQ-26) instead of "not yet named in interfaces.md"; then Wave 5: swap MSW for the real API endpoint by endpoint, OpenAPI-generated types | backend endpoints |

Waves 3–5 and gates G2–G5 are unchanged (§5–§9); they now use the per-date publication of OQ-23.
