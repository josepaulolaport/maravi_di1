# Maravi DI1 — Module-based parallel implementation plan

**Status:** implementation blueprint, 2026-10-18. **Sources of truth:** `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, and the decisions confirmed in conversation (open ones in `docs/open-questions.md`). If these disagree, flag the discrepancy before implementation; do not silently alter domain rules.

## 0. Non-negotiable architecture

- Python 3.12+ / FastAPI / SQLAlchemy 2.x async / PostgreSQL 16+ / Alembic / `uv`. RabbitMQ via `aio-pika`. Docker Compose for API, PostgreSQL, RabbitMQ, processing worker, dispatcher and outbox relay (roles can share a worker process for local simplicity if semantics remain intact).
- React + TypeScript + **Mantine**, TanStack Query. **All user-facing text in pt-BR**; identifiers/source files may be English. No auth. Exactly **one** portfolio, no `portfolio_id` anywhere.
- Modular monolith: `asset`, `pricing`, `ledger`, `prices`, `portfolio`, `pnl`, `processing`; shared technical infrastructure under `platform`. Each module has `public.py`, `application/services`, `application/interfaces` where useful, `domain`, `infrastructure/persistence`, `presentation/http`; create only used files/packages.
- Ownership: Asset owns product/instrument hierarchy and futures specs; Pricing owns **pure** DI1 PU/rate calculations; Ledger owns immutable trade execution values and cash movements; Prices owns manual/B3 reference prices and revisions; Portfolio owns dated `positions`, `position_metrics`, `portfolio_metrics` and frontend read query; PnL owns **pure** attribution and aggregation; Processing owns user-requested jobs, cancellation, preflight, dirty markers and result publication.
- No per-operation command classes, event-sourced rewrite, automatic P&L calculation, one RabbitMQ queue per module, separate Reader/Service class per operation or cross-module imports of private ORM/repositories. Service methods may combine reads and writes. Use narrow `Protocol` interfaces only where useful; dedicated `PortfolioQueryService` is warranted.
- Financial conventions: DI1 challenge rate ↔ PU uses actual calendar days / 365, face value 100,000 (product-configured); source selection MANUAL > B3 exact day only; no price carry-forward; daily calendar processing; zero initial cash/positions/P&L; chronological trades incl. reversals; no deposits/withdrawals in trading P&L. `financial_total = signed_quantity × reference_PU`, AUM = cash + sum signed market value. Positions store just quantity; asset and portfolio metrics in separate tables. Missing prices can leave accounting available but valuation/P&L incomplete.
- Input mutations immediately mark dependent financial state stale **in the same PostgreSQL transaction**; never automatically enqueue processing. Many overlapping queued requests permitted; only one active request; cancellation cooperative. Worker stages daily results and atomically publishes if inputs/claim token still valid. RabbitMQ dispatches work, database owns status/order.
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
    contracts/                 # frozen cross-module DTOs only if genuinely shared
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

Each active module normally implements `public.py`, `dependencies.py` if needed, `domain/`, `application/services/`, `application/interfaces/` when meaningful, `infrastructure/persistence/{models.py,repositories.py,queries/}`, `presentation/http/{router.py,schemas.py}`. Only Processing initially has a messaging consumer. SQL queries belong in Infrastructure. FastAPI `Depends` belongs in HTTP adapters or dependency providers, **never** the application/domain or repositories. Worker constructors use plain Python factories, not FastAPI dependency injection.

## 2. Multi-agent operating model

**Worktree per implementation agent.** A shared **Architect/Integrator** is the only editor of shared composition files, initial Alembic migration, `pyproject.toml`, global API contracts and compose files; it reviews changes to the platform interfaces modules use (UoW, outbox writer), but `platform/**` belongs to lane H (OQ-17). Each module agent edits exclusively `modules/<module>/**` and `tests/unit/<module>/**`, plus agreed integration tests under a dedicated file namespace. The Frontend agent exclusively edits `frontend/**`. The Infrastructure agent edits `platform/**`, `workers/` bootstrap and root configuration in coordination with the integrator. No two agents edit the same file concurrently.

Recommended agents (a reviewer can be a second agent applied after each module PR):

| Lane | Ownership | Starts | Dependencies |
|---|---|---|---|
| A — Asset | `modules/asset/**`, `tests/unit/asset/**` | Wave 1 | Frozen DTOs + schema |
| B — Pricing | `modules/pricing/**`, `tests/unit/pricing/**` | Wave 1 | InstrumentDescriptor contract; can use fixtures |
| C — Ledger | `modules/ledger/**`, `tests/unit/ledger/**` | Wave 2 | Asset & Pricing public interfaces; invalidator protocol |
| D — Prices | `modules/prices/**`, `tests/unit/prices/**` | Wave 2 | Asset & Pricing public interfaces; invalidator protocol |
| E — Portfolio | `modules/portfolio/**`, `tests/unit/portfolio/**` | Wave 1 pure accounting; Wave 3 DB/read | Ledger DTOs; PnL result DTOs; schemas |
| F — PnL | `modules/pnl/**`, `tests/unit/pnl/**` | Wave 1 | Position and Trade DTOs, fixed calculation formulas |
| G — Processing | `modules/processing/**`, `tests/unit/processing/**` | Wave 2 queue API; Wave 4 worker integration | All module public interfaces + platform messaging |
| H — Platform | `platform/**`, `workers/**` shared bootstrap | Wave 0 | Schema and dispatch contract |
| I — Frontend | `frontend/**` | Wave 1 mock API | Frozen HTTP schemas; backend not required |
| X — Integrator | `composition/**`, `main.py`, migrations, global tests, shared contracts, CI, compose | Throughout | Owns all cross-module wiring |

If fewer agents: combine A+B, C+D, E+F; **do not** combine G with platform+integration until there are stable endpoints. A coding agent should not modify another lane's folder to make its tests pass: raise a contract change request to X.

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
- Verify supplied `schema.sql` against disposable PostgreSQL 16+; fix SQL defects before using it as migration baseline. Produce Alembic revision(s) **centrally**, preferably one initial revision incorporating all table DDL. Validate downgrade only where safe and documented.
- Define stable public DTOs: `InstrumentDescriptor`, `TradeRecord`, `CashMovementRecord`, `ReferencePriceRecord`, `PositionState`, `AssetPnLResult`, `PortfolioPnLResult`, `CalculationCompleteness`, `ProcessingRequest`. Do not expose ORM types across modules.
- Freeze rate units (rate `0.135` = 13.5%) and deterministic UTC timestamp vs local business-date semantics. Freeze precision as decided in OQ-3 (34-digit `Decimal`, `ROUND_HALF_UP`, PU 10 dp, rate 12 dp, excess decimals rejected), and the same-day order `(trade_date, trade_time, seq)` with `trade_time` required (OQ-13), and the error contract (OQ-15, `interfaces.md` "Errors").
- Define Unit of Work around one AsyncSession, SQLAlchemy database factory, API/worker bootstrap, error types, Pydantic API schemas, exceptions mapping.
- Define public invalidation contract `ledger_changed(effective_date, uow)` and `prices_changed(asset_id, date, uow)`; Processing agent owns implementation, but Ledger/Prices agents can use an in-memory fake now.
- Add baseline lint/type/test commands (ruff, pytest, optional mypy/pyright, migration smoke test). Set import boundary tests.
- Agree exact price input enum (`PU` or `RATE`), source precedence and reference-price revision strategy.

**Gate 0:** package imports and app starts, migration applies to fresh DB, cross-module contract examples compile, all agent lanes can branch from identical contract commit. Do not parallelize shared DTO design before this freeze.

## 4. Wave 1 — independent domain engines (parallel)

### A. Asset
- Implement `instrument_types`, `asset_classes`, `products`, `futures`, `instruments` models/repositories/validation and `AssetService`/`public.py`.
- Validate `FUTURE → INTEREST_RATE_FUTURE → DI1 → DI1F27` hierarchy, product spec product-level, maturity instrument-level, case-insensitive unique codes, futures spec only for FUTURE product.
- Tests: invalid hierarchy, duplicate codes, missing maturity, futures spec lookup, contract DTO.
- **Done:** Asset public API can supply full DI1 descriptor for trade and pricing calculators.

### B. Pricing
- Pure DI1 calculator, signed Decimal inputs and exact DC/365 formula; inverse rate from PU; reference date/maturity validation and input-kind handling; explicit rounding rules once approved.
- Calculation response with methodology/version; no repositories, queues or PnL.
- Tests: challenge example, forward/inverse tolerance, leap-year/calendar-day count, zero remaining days, nonpositive PU, invalid rate, Decimal stability.
- **Done:** same calculator callable without FastAPI or DB.

### E. Portfolio (domain only)
- Pure chronological daily accounting engine using yesterday's state and day's sorted events; signed quantity, weighted-average PU/rate, partial close, flat and reversing trade, cash balance.
- Avg PU and rate are carried accounting inputs, even though persisted in `position_metrics`; cannot depend on market price presence.
- Tests: open/increase/partial-close/full-close/reversal/short, multiple same-day trades, backdated sequences, deposits/withdrawals; assert PnL never directly changes cash.
- **Done:** reconstructs accounting state for arbitrary fixture dates without infrastructure.

### F. PnL
- Pure per-asset `position_pnl = prior_quantity × (PU_today − PU_prior)` where required; `trades_pnl = Σ signed_trade_qty × (PU_today − execution_PU)`; aggregate only complete expected assets; cumulative chain invalid if previous day unavailable.
- Unit tests for long, short, same-day roundtrip, missing prior/current PU, zero positions, incomplete asset, incomplete chain; no cash-flows in PnL.
- **Done:** calculator returns explicit missing/completeness states and no persistence.

### I. Frontend (mock contracts)
- Implement existing pt-BR screens using Mantine and TanStack Query against typed mock API fixtures: Ativos, Lançamentos, Carteira, Central de Controle/Pendências/Processamentos.
- Handle stale/incomplete metric chips, pending/queued/running/cancelling/cancelled, cancel and replace action, range preview and percentage progress.
- **Done:** screens demonstrate full flows with mock adapters before backend integration.

## 5. Wave 2 — input persistence + processing request API (parallel)

### C. Ledger
- `LedgerService` and repository, create/list/delete immutable trades and cash movements; deterministic transaction order; automatic PU/rate conversion via Pricing, product lookup via Asset.
- Only immutable economic fields; deletion audit. Each write invokes Processing invalidation inside SAME UoW; no recalculation enqueue.
- Tests: atomic rollback if invalidation fails, multiple trades same date, soft-delete idempotence, execution price not added to `prices.reference_prices`.

### D. Prices
- `PriceService`: create current manual/B3 observation, supersede, removal, preferred-by-source exact-date batch reads, unique active per `(asset,date,source)`.
- Prefer MANUAL over B3; if removed, B3 becomes preferred. No silent older-date fallback. Price writes invalidate relevant financial results in same UoW.
- Tests: revision audit, race/unique constraint, preferred-source priority, no carry-forward, absence of auto-processing, revision-bound observations.

### G. Processing (request API subset)
- `ProcessingService` enqueue/list/get/cancel/cancel-and-replace, `FinancialResultInvalidator`, dirty markers and revisions, missing-price issue contract.
- Support overlapping QUEUED ranges in PostgreSQL, one active global job invariant; queued cancel immediately, running cancel sets cancellation marker.
- Tests: concurrent enqueue, atomic cancel+replace, stale data invalidation, source revision advance.

### H. Platform (messaging subset)
- UoW, outbox write/relay with publisher confirms, inbox idempotency, aio-pika consumers, retry and failure policy, SQL-controlled dispatch leases/fencing.
- Tests: simulated relay crash and resend, duplicate delivery, ACK after durability, reconnect. Keep messaging adapters outside business services.

**Gate 2:** Create manual reference price and trade, read back independently, verify invalidation but **no** processing request was automatically created. Concurrent queued jobs can be inserted/cancelled.

## 6. Wave 3 — portfolio persistence and consolidated reads

**Portfolio lane E**, integrating with C, D, F and X:
- Persist `positions(asset_id, position_date, quantity)`, `position_metrics(asset_id, metric_date, avg PU/rate, ref PU/id, financial_total, position/trades/daily PnL, status)`, `portfolio_metrics(metric_date, cash, positions market value, AUM, portfolio PnL/status)`.
- `PortfolioQueryService` returns one assembled frontend table; indexed read SQL in Portfolio Infrastructure only. Join published asset records and metrics by asset+date; include processing validity status. Don't mix new/current reference price into old result.
- Make read output distinguish `0`, `null`, `stale`, `unprocessed`, and `completed_with_issues`.
- Implement stage and publish operations against `processing.staged_*` through a narrow collaboration contract with Processing. **Ownership (OQ-8):** the `staged_*` tables are in the `portfolio` schema and owned by Portfolio; Processing calls `stage_day` / `publish_range` through `public.py`.
- Tests: exact-day joins, null handling, average cost survives missing references, AUM computation, read consistency.

**Gate 3:** Portfolio table/summary available from seeded historical data with correct accounting and missing-price flags.

## 7. Wave 4 — processing worker + integration

**Processing lane G** with Platform lane H, Portfolio lane E, Integrator X:
- `ProcessingDispatcher`: lock singleton calculation state; select oldest eligible queued job; set `DISPATCHED` and outbox command atomically. One active global job (even if broker duplicates messages).
- `PortfolioRangeProcessor`: worker claim token + lease; process exactly the requested range (OQ-11: if start−1 is stale or missing, still run and publish flagged stale with null P&L and a `STALE_PREDECESSOR` issue); iterate **every calendar day**; order ledger events; call portfolio accounting, preferred exact-day Prices, PnL calculators; persist staged daily rows and status/progress.
- On cancellation request, stop at day boundary, mark cancelled, discard staging; queued requests can be cancelled without broker work.
- Before publication, lock job/control state, verify claim token, no cancellation, source revisions still compatible, expected range and dependency completeness; atomically upsert all three Portfolio published tables, retire/deletes obsolete dated rows as required, update dirty markers and request outcome.
- On changed inputs while running: `SUPERSEDED`; never publish stale run as current. On missing prices: preserve accounting, record `issues`, publish `COMPLETED_WITH_ISSUES` with null dependent metrics; do not retry domain-data gaps.
- On process death: lease expiry/recovery, idempotent dispatch/inbox and fencing; no concurrent global workers even if multiple processes.
- **Test adversarial sequences:** queue A, create backdated trade, queue B, cancel A, finish B; duplicate deliveries; crash after outbox publish; crash mid-date; cancellation while staging; source mutation just before publish; missing Saturday price; transaction atomicity of all three tables; no partial published view.

**Gate 4:** Docker Compose e2e: new trade/price invalidates, user queues job, sees progress, cancels/replaces, published position table and AUM/PnL reflect only complete valid writes.

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
- **G2** C+D+G(request)+H broker plumbing, same-UoW invalidation tested; no auto-recalc.
- **G3** Portfolio persistence/read models, dates+missing data correct.
- **G4** dispatch → worker → staging → publication; cancel + overlapping requests, stale fencing tested.
- **G5** frontend integrated, all e2e/constraints/documentation, Docker run reproducible.

Do not merge branches merely because code compiles. Require reviewer sign-off and tests. Use API/DTO contract tests to avoid coordination by shared ORM classes.

## 10. Agent handoff template (copy for each lane)

> You are the **[LANE]** implementation agent for Maravi DI1. Read `docs/maravi_business_specification.md`, `docs/schema.md`, `docs/schema.sql`, `docs/interfaces.md`, `docs/maravi_implementation_plan.md` and `docs/open-questions.md`. Own ONLY `[allowed directories]`. Implement Wave `[N]` deliverables for `[module]`. Preserve single-portfolio, exact-date prices (MANUAL > B3), DC/365, no automatic processing and transactional invalidation. Communicate only through frozen `public.py`/DTO contracts; no private cross-module imports; domain calculators pure; SQL in Infrastructure; `Depends` HTTP-only. Do not create/edit Alembic revisions or shared composition config: raise an integration request to X. Add focused unit tests and contract tests. Report changed files, commands/tests run, unresolved contract questions, deviations from spec, and edge cases. Stop if you discover ambiguity in settlement/multiplier rules; don't invent conventions.

**Reviewer prompt:** Independently compare the agent diff to its frozen interfaces, schema and acceptance tests. Search for invisible auto-recalculation, race conditions, stale published results, duplicates, incorrect Decimal/365 math, incorrect sign on shorts, missing-price zero fallbacks, direct module-internal imports, and unauthorized edits outside the lane. Produce prioritized actionable findings; request correction and re-review.

## 11. Open decisions requiring human sign-off before relevant code

Items 1–4 below were answered on 2026-10-18 (`docs/open-questions.md`); only OQ-18 (challenge discrepancies) remains open.

1. Precision/rounding — OQ-3.
2. Maturity settlement — OQ-1.
3. Multiplier — OQ-2.
4. Zero-day trades and non-business dates — OQ-1, OQ-7.

**Post-completion TODO:** asynchronous CSV reference-price import and optional B3 extraction feeding `PriceService` via RabbitMQ adapter, not part of initial implementation.
