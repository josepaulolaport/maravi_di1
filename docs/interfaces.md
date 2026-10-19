# Maravi DI1 — Module contracts and execution boundaries

**Status:** Implementation target. Consistent with `schema.md` (2026-10-18). This document specifies service ownership and call semantics, not actual Python implementations.

## Scope and structural rules

Single portfolio (no `portfolio_id`). Modular monolith: `asset`, `ledger`, `pricing`, `prices`, `portfolio`, `pnl`, `processing`. HTTP/API service methods may be async; calculation engines are deterministic synchronous pure Python. `platform` owns database session/UoW, RabbitMQ/outbox/inbox, tracing. Cross-module access only through `public.py` contracts. No service imports another module's repositories/ORM. `Depends` only in FastAPI adapters/dependency providers. SQL lives in `infrastructure/persistence/queries`. One shared Unit of Work for operations that must save both a business mutation and financial-result invalidation.

## Contract catalog

### Asset
- `AssetReader.get_instrument(instrument_id) -> InstrumentDescriptor`
- `AssetReader.get_instruments(ids) -> Mapping[id, InstrumentDescriptor]`
- `AssetService.create_product(request)`, `create_instrument(request)`, `get_instrument(...)`, `list_instruments(...)`
- `InstrumentDescriptor`: id, code, product_id, instrument_type, asset_class, maturity_date, face_value, multiplier, settlement_method.
- Asset validates product/class/type hierarchy and maturity requirements. Futures' shared specs in `asset.futures`, contract maturity in `asset.instruments`.

### Pricing
- `PricingService.calculate(instrument: InstrumentDescriptor, reference_date, quote: Quote) -> Price`
- `Quote` is what was typed, the single authoritative input: a rate or a PU. `Price` is the complete pair: PU, rate and input_kind, neither optional. The only convention is DC/365 (spec §4.1).
- `DI1Calculator` is pure and returns a value. Calculators never publish messages or persist results. `PriceService` and `LedgerService` can both call Pricing's public interface; P&L does **not** belong here.

### Ledger
- `LedgerService.create_trade(request, *, uow) -> Trade`
- `LedgerService.delete_trade(trade_id, reason, *, uow) -> None` (soft delete)
- `LedgerService.create_cash_movement(request, *, uow) -> CashMovement`
- `LedgerService.delete_cash_movement(id, reason, *, uow) -> None`
- `LedgerReader.get_trades(start_date, end_date) -> ordered list[Trade]`
- `LedgerReader.get_cash_movements(start_date, end_date) -> ordered list[CashMovement]`
- Writes validate Asset and use Pricing when entry is rate-only or PU-only. Validation (OQ-1, OQ-13, OQ-14): `trade_time` required; nothing dated after today (São Paulo, injected clock); a trade may be dated up to the maturity date inclusive (on it the PU is typed and the rate stored as 0), never after; bounds are only the schema CHECKs. Execution PU/rate are stored on the immutable trade. Ledger never creates reference prices. Input writes synchronously invalidate accounting from effective date in the same DB transaction, but never enqueue P&L work.

### Prices
- `PriceService.set_reference_price(request, *, uow) -> ReferencePrice`
- `PriceService.supersede_reference_price(...) -> ReferencePrice` (new revision, never overwrite economic values)
- `PriceService.remove_current_reference_price(...)` (supersede/remove availability according to audit policy)
- `PriceReader.get_preferred(asset_id, reference_date) -> ReferencePrice | None`
- `PriceReader.get_preferred_many(asset_ids, dates) -> mapping`
- Reference prices may be dated up to the maturity date inclusive (PU typed on it, rate 0), never after it or after today (OQ-1, OQ-14). After maturity the reference PU is 0 by definition and no observation exists.
- Preferred current source order: MANUAL, then B3. Exactly the requested calendar date; no carry-forward. One current observation per (asset, date, source), superseded rows retained. Reference price IDs are returned to consumers for reproducibility. Price writes invalidate valuation/P&L dependencies but not quantities, in the same transaction; never automatically enqueue processing. Future bulk import can call the same PriceService via a separate RabbitMQ adapter.

### Portfolio
Pure domain calculators (`portfolio/domain/`, frozen dataclasses). Two independent chains read the same Ledger facts and never each other's output (OQ-21); the application layer maps `ledger.public.TradeRecord` onto Portfolio's own `Trade(asset_id, trade_date, trade_time, seq, signed_quantity, execution_pu, execution_rate)`, ordered by `(trade_date, trade_time, seq)` (OQ-13). A skipped day or misdated event raises the internal `AccountingError`, not a `DomainError`.
- **Positions chain** (no cash, no prices): `PositionsEngine.calculate_day(previous_state: PositionState, trades, date) -> PositionsDay` and `calculate_range(previous_state, trades, end_date) -> tuple[PositionsDay, ...]`. `PositionState(as_of, positions: tuple[OpenPosition, ...])` holds `OpenPosition(asset_id, quantity ≠ 0, average_entry_pu, average_entry_rate)`; `PositionDay(asset_id, previous_quantity, quantity, average_entry_pu, average_entry_rate, trades)` exists exactly for the expected assets (OQ-10), quantity 0 included, with averages `None` when flat. Averages are rounded at each day's close (PU 10 dp, rate 12 dp, OQ-3) and carried forward as stored, so one job over [A, B] equals several jobs that read the previous day back.
- **Cash chain** (no positions, no prices): `CashCalculator.calculate_day(previous_balance: CashBalance, trades, deposits: Decimal, withdrawals: Decimal, date) -> CashDay` and `calculate_range(previous_balance, trades, deposits: Mapping[date, Decimal], withdrawals: Mapping[date, Decimal], end_date) -> tuple[CashDay, ...]`. `deposits`/`withdrawals` are the day's totals, summed by the application from `LedgerReader.get_cash_movements` (`0` when none, never negative; a date absent from the maps means none). `CashDay(date, previous_cash_balance, trades_cash_flow, deposits, withdrawals, cash_balance)` with `trades_cash_flow = −Σ(signed_qty × execution_PU)`: one `cash_balances` row.
- **Valuation**: `ValuationCalculator.calculate_day(date, assets: Sequence[AssetValuationInput], cash_balance: Decimal | None) -> PortfolioValuation`. `AssetValuationInput(asset_id, quantity, maturity_date, reference_pu, reference_price_id)`: a PU and the id of its observation go together or not at all (OQ-9); past maturity the caller passes neither. Per asset `AssetValuation(asset_id, reference_pu, reference_price_id, financial_total = Q × reference_PU, status)` with `status` COMPLETE, MISSING or NOT_REQUIRED: Q ≠ 0 without a price is MISSING and `null`; Q = 0 is worth 0, NOT_REQUIRED; after maturity the PU is 0 by definition, COMPLETE, with no observation id (OQ-1). `PortfolioValuation(date, assets, positions_market_value, aum, status)`: the market value is `null` if any asset is MISSING (never a partial sum), and AUM = cash + market value, `null` when either side is missing. No multiplier (OQ-2).
- `PortfolioAccounting.calculate_day(previous_state: AccountingState, trades, deposits, withdrawals, date) -> AccountingDay(cash: CashDay, positions_day: PositionsDay)` and `calculate_range(previous_state, trades, deposits: Mapping[date, Decimal], withdrawals: Mapping[date, Decimal], end_date) -> tuple[AccountingDay, ...]` run both chains over the same days, for an ALL scope only; `AccountingState(as_of, cash_balance, positions)`.
- Predecessor readers, one per chain (OQ-21, OQ-22): `PortfolioReader.get_previous_positions(before_date)` → the `PositionState` published for `before_date − 1` with its stale flag, or none; `get_previous_cash(before_date)` → the `CashBalance` from the published `cash_balances` row of `before_date − 1` with its stale flag, or none. A POSITIONS job reads only the first, a CASH job only the second, an ALL job both.
- `PortfolioReader.get_positions(date) -> list[Position]`
- `PortfolioQueryService.get_position_table(date) -> PositionTableView`
- `PortfolioQueryService.get_summary(date) -> PortfolioSummaryView`
- `PortfolioResultsWriter` stages per chain: `stage_positions_day(request_id, PositionsDay, asset_metrics, portfolio_metrics, *, uow)` for POSITIONS and `stage_cash_day(request_id, CashDay, *, uow)` for CASH (ALL calls both), then `publish_range(request_id, scope, requested_range, *, uow)` publishes the scope's tables and recomputes `aum` for the range from the other chain's published value (OQ-21). Portfolio owns the `portfolio.staged_*` tables (OQ-8); Processing calls these through `public.py`.
- Portfolio owns published `positions`, `position_metrics`, `portfolio_metrics`, `cash_balances` and their staging representations; daily quantities and average costs remain calculable with missing reference prices. AUM = cash (`cash_balances`) + sum signed position market values (`portfolio_metrics`), `null` when either side is missing, stale when either side is stale. No exposure or `total_equity` fields. Rows exist for D exactly for expected assets: Q[D−1] ≠ 0 or a trade on D, including quantity 0 (OQ-10). The D−1 reference PU is read from D−1's `position_metrics` row (OQ-9). Published read models join documented read surfaces by date and asset; never recombine latest Prices observations with older P&L.

### PnL
- `AssetPnLCalculator.calculate(previous_position, day_trades, previous_reference_pu, current_reference_pu) -> AssetPnLResult`
- `PortfolioPnLCalculator.aggregate(expected_assets, asset_results, previous_cumulative) -> PortfolioPnLResult`
- Pure functions; no persistence or messaging adapters required initially.
- First day: when Q[D−1] = 0, `position_pnl` is exactly 0 and needs no D−1 price (OQ-4). After maturity the current reference PU is 0 (OQ-1). Precision: 34-digit `Decimal`, `ROUND_HALF_UP` (OQ-3). The multiplier is not applied (OQ-2).
- P&L uses daily Position P&L + Trades P&L attribution; deposits/withdrawals do not enter P&L. Missing required price => incomplete/null P&L, never silently zero or sum just available assets. Cumulative chain unavailable after an unresolved gap.

### Processing
- `FinancialResultInvalidator.trades_changed(effective_date, *, uow)` (cash and positions stale from the date), `cash_movements_changed(effective_date, *, uow)` (cash only) and `prices_changed(asset_id, reference_date, *, uow)` (valuation only) (OQ-21). Each bumps the matching revision (`trades_revision`, `cash_movements_revision`, `prices_revision`) and marker.
- `ProcessingService.preview_range(scope, start_date, end_date) -> ProcessingPreview` — the range is exactly [start, end] (OQ-11); the preview flags when the start−1 state of the scope's chain is stale or missing. `scope` ∈ {CASH, POSITIONS, ALL} (OQ-21).
- `ProcessingService.enqueue_range(scope, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.request_cancel(request_id, *, uow) -> ProcessingRequest`
- `ProcessingService.cancel_and_replace(active_id, scope, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.list_requests()`, `get_request(id)`, `get_issues(...)`
- `ProcessingDispatcher.dispatch_next() -> Optional[request_id]`: transactionally claim singleton `calculation_state` row, set job DISPATCHED, record outbox command.
- `PortfolioRangeProcessor.run(request_id, claim_token)`: claim/lease (60 s, renewed per day, OQ-5), capture the latest input revisions of its scope, process exactly the requested dates (each chain checks its own start−1: positions stale or missing, or cash stale, still run and publish flagged stale — positions with `pnl_status = MISSING` — with a `STALE_PREDECESSOR` issue naming the chain; cash never published: see the predecessor rule below; OQ-11, OQ-21, OQ-22), loop one calendar day at a time, calculate the scope's chains (CASH: `CashCalculator`; POSITIONS: `PositionsEngine`, Prices, `ValuationCalculator`, PnL; ALL: both), stage results/progress; check cancellation between dates and before publication; publish only with matching input revisions and active fencing token; then finish job. No nested RabbitMQ message per asset or per day.
- Issue types: `MISSING_REFERENCE_PRICE`, `EXPIRED_OPEN_POSITION`, `STALE_PREDECESSOR`; a `STALE_PREDECESSOR` names its chain (`CASH` or `POSITIONS`, OQ-22).
- Predecessor rule (OQ-22): a CASH or ALL job whose start−1 has no published cash while an active trade or cash movement is dated on or before start−1 publishes nothing and ends `FAILED` with `error_code = CASH_PREDECESSOR_MISSING`; stale cash at start−1 publishes flagged stale. Checked when the job starts; enqueueing is never refused for it.
- Cancellation of queued work is immediate. Running cancellation sets a request marker; worker stops safely and discards staged data. Overlapping requests allowed in PostgreSQL, one active global job.

## Transaction boundaries and behavior

1. **Mutation:** HTTP handler opens UoW; Ledger or Prices writes authoritative record; Processing invalidator updates revision/dirty metadata using same session; one COMMIT; return response. No automatic processing job.
2. **Enqueue:** HTTP handler opens UoW; Processing validates requested dates; insert `requests(status=QUEUED)`; COMMIT; return job ID. Do not publish one Rabbit message per enqueued job.
3. **Dispatch:** dispatcher under row lock selects oldest eligible QUEUED request by (created_at, id), sets singleton active ID and DISPATCHED, saves outbox command in same transaction, COMMIT. Outbox relay publishes with confirms.
4. **Execute:** worker claims specific dispatched job using claim token and time-bounded lease, starts from latest committed inputs, iterates by calendar date and saves run-scoped staged rows. Processing controls transaction durations; calculators have no DB side effects.
5. **Cancel:** request cancel flag committed, worker checks between date commits; cancel queued jobs before dispatch; cancelled run's staging is discarded. A crash/timeout lease recovery is explicit.
6. **Publish:** transaction obtains processing singleton lock, verifies claim token/cancellation and the scope's input revisions (CASH: trades + cash movements; POSITIONS: trades + prices; ALL: all three), atomically upserts the scope's published tables for the requested range and recomputes `aum` there from the other chain's published value, replaces stale dated rows where necessary, updates dirty status carefully, and marks job complete or with issues. On source revision mismatch, discard staging and mark SUPERSEDED. Make outputs visible together.
7. **Broker semantics:** RabbitMQ delivery at-least-once. Inbox idempotency plus request/status/claim fencing guards duplicate delivery. ACK only after durable state transition. Retries transient only; domain missing prices are `COMPLETED_WITH_ISSUES`, not retries. Relay and dispatcher recover after crashes.

**Dirty marker rule (OQ-12, OQ-21):** markers are per chain — `cash_dirty_from`, `positions_dirty_from`, `valuation_dirty_from`. After a publish of [A, B] with the scope's revisions unchanged since the start, a marker of that scope within [A, B] advances to B+1 (CASH: cash; POSITIONS: positions and valuation; ALL: all three); a marker before A stays; days after B remain stale until processed.

**Dirty marker caution:** If old published results are retained while stale, Portfolio query responses must include validity metadata. A single `valuation_dirty_from` may overinvalidate; later introduce asset/date-granular dependencies if needed. Clearing markers must account for any still-unprocessed dirty dates and queued work.

## HTTP endpoints

- `GET /health` (and `HEAD`): `200 {"status": "ok"}` when PostgreSQL answers `SELECT 1` within a short timeout (2 s); otherwise `503` problem+json ("Serviço indisponível", "O banco de dados não está acessível."), nothing of the error in the body. Served by `composition/health.py`; the app is built by `di1.main:create_app` (uvicorn `--factory`).

- `POST /trades`, `DELETE /trades/{id}`, `GET /trades`
- `POST /cash-movements`, `DELETE /cash-movements/{id}`, `GET /cash-movements`
- `POST /reference-prices`, `GET /reference-prices`, `DELETE /reference-prices/{id}` (audit-preserving removal)
- `GET /portfolio/positions?date=YYYY-MM-DD`, `GET /portfolio/summary?date=YYYY-MM-DD`, `GET /portfolio/pnl?start_date=&end_date=` (the published `portfolio_metrics` series: per date `cumulative_pnl`, `daily_pnl`, statuses and stale flag; feeds the Carteira cumulative chart, no per-asset data; OQ-16)
- `POST /processing/requests`, `GET /processing/requests`, `GET /processing/requests/{id}`, `POST /processing/requests/{id}/cancel`, `POST /processing/requests/{id}/cancel-and-replace`
- `GET /instruments`, `POST /instruments`, `GET /products`, `POST /products`; direct `POST /pricing/calculate` for previews if needed (the current UI shows no preview: the complementary PU or rate is computed when an entry is saved, OQ-19).
- **UI read needs (OQ-19, OQ-20).** The frontend's draft contract (lane I) proposes how each is served; the integrator fixes route names and shapes:
  - Pendências list: an HTTP route for `ProcessingService.get_issues`, three issue types only.
  - Range preview: an HTTP route for `ProcessingService.preview_range` (scope, exact [A, B], number of days, and per chain of the scope whether start−1 is stale or missing; a missing cash start−1 warns that the job will end `CASH_PREDECESSOR_MISSING`; OQ-21, OQ-22).
  - Processing request read: requested range, status, days done and total, the date being processed, created/started/finished times and the error message, if any.
  - Ativos catalogue: instrument types and asset classes, and per product its class, type and number of contracts.
  - Contract list: per instrument, its latest current reference observation `{date, pu, rate, source}`, or `null`.
  - Reference prices: the source of each observation and the revision history for an (asset, date).
  - Trades: both execution PU and execution rate.
  - Lançamentos cash strip: `GET /portfolio/summary` for the range end date and the day before; the cash comes from `cash_balances`, with the cash chain's own stale and unprocessed flags (OQ-21).
  - Processing scope: the request form and list carry `scope` (CASH, POSITIONS, ALL; UI labels Caixa, Posições, Tudo), and the summary reports cash freshness separately from positions and valuation (OQ-21).
- All UI-facing content/labels in pt-BR; schema, internal interfaces, and Python identifiers remain English.

### Errors (OQ-15)

Every error response is RFC 9457 `application/problem+json`:

```json
{"type": "about:blank", "title": "…", "status": 422, "detail": "…",
 "errors": [{"code": "FUTURE_DATE", "message": "A data não pode ser posterior a hoje.", "field": "trade_date"}]}
```

`message` is pt-BR; `code` is English. Catalogue (extended additively by the integrator):

| Code | Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Malformed or out-of-bounds input (schema CHECK rules, too many decimals) |
| `FUTURE_DATE` | 422 | An entry or price dated after today (São Paulo) |
| `CONTRACT_MATURED` | 422 | A trade or reference price dated after the instrument's maturity |
| `NOT_FOUND` | 404 | The resource does not exist |
| `INVALID_RANGE` | 422 | A processing or query range with start after end |
| `JOB_NOT_CANCELLABLE` | 409 | Cancel requested for a job that is already finished |

## DI composition

`modules/<name>/public.py` exposes stable read/service contracts and DTOs; `modules/<name>/dependencies.py` creates module-local implementations; `composition/dependencies.py` wires cross-module collaborators and UoW; `composition/routers.py` registers routes; `composition/consumers.py` registers handlers; workers use plain factories, not FastAPI `Depends`. No one-class-per-command framework; cohesive application services.

## Implementation/verification order

1. Asset, Pricing, Ledger and Prices; Decimal calculations and immutable inputs with synchronous invalidation.
2. Portfolio accounting state and PnL pure calculators; exact-date missing price rules, reversal tests.
3. Portfolio published tables and one-query consolidated frontend read models.
4. Processing requests, staging, dispatch/outbox/inbox, cancellation and publication/revision fencing.
5. Integration tests for competing overlapping requests, cancel and replace, crashes, stale publishes, missing prices, weekend handling, 365-day pricing.
6. Future TODO (not part of challenge MVP): asynchronous CSV/B3 ingestion via same Prices service.

**Decided on 2026-10-18** (see `open-questions.md`): maturity (OQ-1), multiplier (OQ-2), precision (OQ-3). **Still not invented:** external official-price ingestion (post-delivery TODO).
