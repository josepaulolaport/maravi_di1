# Maravi DI1 — Module contracts and execution boundaries

**Status:** Implementation target. Consistent with `schema.md` (2026-10-18). This document specifies service ownership and call semantics, not actual Python implementations.

## Scope and structural rules

Single portfolio (no `portfolio_id`). Modular monolith: `asset`, `ledger`, `pricing`, `prices`, `portfolio`, `pnl`, `processing`. HTTP/API service methods may be async; calculation engines are deterministic synchronous pure Python. `platform` owns database session/UoW, RabbitMQ/outbox/inbox, tracing. Cross-module access only through `public.py` contracts. A value read by more than one module is defined once in `di1.shared` and exposed by its owner's `public.py`; consumers never redeclare it (see "Shared values"). No service imports another module's repositories/ORM. `Depends` only in FastAPI adapters/dependency providers. SQL lives in `infrastructure/persistence/queries`. One shared Unit of Work for operations that must save both a business mutation and financial-result invalidation.

## Contract catalog

### Asset
- `AssetReader.get_instrument(instrument_id) -> InstrumentDescriptor`
- `AssetReader.get_instruments(ids) -> Mapping[id, InstrumentDescriptor]`
- `AssetService.create_product(request)`, `create_instrument(request)`, `get_instrument(...)`, `list_instruments(...)`
- `InstrumentDescriptor`: id, code, product_id, instrument_type, asset_class, maturity_date, face_value, multiplier, settlement_method.
- Asset validates product/class/type hierarchy and maturity requirements. Futures' shared specs in `asset.futures`, contract maturity in `asset.instruments`.

### Pricing
- `PricingService.calculate(instrument: InstrumentDescriptor, reference_date, input: PricingInput) -> PricingResult`
- `PricingInput` has exactly one authoritative input: rate or PU. `PricingResult` returns PU, rate where derivable, methodology (`CHALLENGE_DC_365`), version, input_kind.
- `DI1Calculator` is pure and returns a value. Calculators never publish messages or persist results. `PriceService` and `LedgerService` can both call Pricing's public interface; P&L does **not** belong here.

### Shared values
- `di1.shared.trades.Trade`: the economic facts of a trade — `asset_id`, `trade_date`, `trade_time`, `seq`, `signed_quantity` (buys positive), `execution_pu`, `execution_rate`, and `order_key` = `(trade_date, trade_time, seq)` (OQ-13). Owned by Ledger, read by Portfolio, PnL and Processing. No module declares its own trade type.
- `di1.shared.decimals` (precision, OQ-3) and `di1.shared.clock` (injected clock).

### Ledger
- `LedgerService.create_trade(request, *, uow) -> TradeRecord` (`TradeRecord` carries the shared `Trade` plus Ledger's metadata: id, input kind, created_at, deletion audit)
- `LedgerService.delete_trade(trade_id, reason, *, uow) -> None` (soft delete)
- `LedgerService.create_cash_movement(request, *, uow) -> CashMovement`
- `LedgerService.delete_cash_movement(id, reason, *, uow) -> None`
- `LedgerReader.get_trades(start_date, end_date) -> list[Trade]` (shared `Trade`, active only, ordered by `order_key`)
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
- `PortfolioAccounting.calculate_day(previous_state, trades: Sequence[Trade], deposits: Decimal, withdrawals: Decimal, date) -> AccountingDay`. Cash movements are Ledger facts: Portfolio receives only the day's deposit and withdrawal totals (`0` when none, never negative), summed by the caller from `LedgerReader.get_cash_movements`.
- `PortfolioReader.get_previous_valid_accounting_state(before_date) -> AccountingState`
- `PortfolioReader.get_positions(date) -> list[Position]`
- `PortfolioQueryService.get_position_table(date) -> PositionTableView`
- `PortfolioQueryService.get_summary(date) -> PortfolioSummaryView`
- `PortfolioResultsWriter.stage_day(request_id, AccountingDay, asset_metrics, portfolio_metrics, *, uow)` and `publish_range(request_id, requested_range, *, uow)`. Portfolio owns the `portfolio.staged_*` tables (OQ-8); Processing calls these through `public.py`.
- Portfolio owns published `positions`, `position_metrics`, `portfolio_metrics` and their staging representations; daily quantities and average costs remain calculable with missing reference prices. AUM = cash + sum signed position market values, nullable when required prices missing. No exposure or `total_equity` fields. Rows exist for D exactly for expected assets: Q[D−1] ≠ 0 or a trade on D, including quantity 0 (OQ-10). The D−1 reference PU is read from D−1's `position_metrics` row (OQ-9). Published read models join documented read surfaces by date and asset; never recombine latest Prices observations with older P&L.

### PnL
- `AssetPnLCalculator.calculate(previous_position, day_trades: Sequence[Trade], previous_reference_pu, current_reference_pu) -> AssetPnLResult` (shared `Trade`)
- `PortfolioPnLCalculator.aggregate(expected_assets, asset_results, previous_cumulative) -> PortfolioPnLResult`
- Pure functions; no persistence or messaging adapters required initially.
- First day: when Q[D−1] = 0, `position_pnl` is exactly 0 and needs no D−1 price (OQ-4). After maturity the current reference PU is 0 (OQ-1). Precision: 34-digit `Decimal`, `ROUND_HALF_UP` (OQ-3). The multiplier is not applied (OQ-2).
- P&L uses daily Position P&L + Trades P&L attribution; deposits/withdrawals do not enter P&L. Missing required price => incomplete/null P&L, never silently zero or sum just available assets. Cumulative chain unavailable after an unresolved gap.

### Processing
- `FinancialResultInvalidator.ledger_changed(effective_date, *, uow)` and `prices_changed(asset_id, reference_date, *, uow)`
- `ProcessingService.preview_range(start_date, end_date) -> ProcessingPreview` — the range is exactly [start, end] (OQ-11); the preview flags when the state of start−1 is stale or missing.
- `ProcessingService.enqueue_range(start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.request_cancel(request_id, *, uow) -> ProcessingRequest`
- `ProcessingService.cancel_and_replace(active_id, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.list_requests()`, `get_request(id)`, `get_issues(...)`
- `ProcessingDispatcher.dispatch_next() -> Optional[request_id]`: transactionally claim singleton `calculation_state` row, set job DISPATCHED, record outbox command.
- `PortfolioRangeProcessor.run(request_id, claim_token)`: claim/lease (60 s, renewed per day, OQ-5), capture the latest input revisions, process exactly the requested dates (if start−1 is stale or missing, still run, publish with `pnl_status = MISSING` and a `STALE_PREDECESSOR` issue: OQ-11), loop one calendar day at a time, calculate Portfolio accounting, retrieve Prices, calculate PnL, stage results/progress; check cancellation between dates and before publication; publish only with matching input revisions and active fencing token; then finish job. No nested RabbitMQ message per asset or per day.
- Issue types: `MISSING_REFERENCE_PRICE`, `EXPIRED_OPEN_POSITION`, `STALE_PREDECESSOR`.
- Cancellation of queued work is immediate. Running cancellation sets a request marker; worker stops safely and discards staged data. Overlapping requests allowed in PostgreSQL, one active global job.

## Transaction boundaries and behavior

1. **Mutation:** HTTP handler opens UoW; Ledger or Prices writes authoritative record; Processing invalidator updates revision/dirty metadata using same session; one COMMIT; return response. No automatic processing job.
2. **Enqueue:** HTTP handler opens UoW; Processing validates requested dates; insert `requests(status=QUEUED)`; COMMIT; return job ID. Do not publish one Rabbit message per enqueued job.
3. **Dispatch:** dispatcher under row lock selects oldest eligible QUEUED request by (created_at, id), sets singleton active ID and DISPATCHED, saves outbox command in same transaction, COMMIT. Outbox relay publishes with confirms.
4. **Execute:** worker claims specific dispatched job using claim token and time-bounded lease, starts from latest committed inputs, iterates by calendar date and saves run-scoped staged rows. Processing controls transaction durations; calculators have no DB side effects.
5. **Cancel:** request cancel flag committed, worker checks between date commits; cancel queued jobs before dispatch; cancelled run's staging is discarded. A crash/timeout lease recovery is explicit.
6. **Publish:** transaction obtains processing singleton lock, verifies claim token/cancellation and relevant input revisions, atomically upserts published positions and both metrics tables for the requested range, replaces stale dated rows where necessary, updates dirty status carefully, and marks job complete or with issues. On source revision mismatch, discard staging and mark SUPERSEDED. Make outputs visible together.
7. **Broker semantics:** RabbitMQ delivery at-least-once. Inbox idempotency plus request/status/claim fencing guards duplicate delivery. ACK only after durable state transition. Retries transient only; domain missing prices are `COMPLETED_WITH_ISSUES`, not retries. Relay and dispatcher recover after crashes.

**Dirty marker rule (OQ-12):** after a publish of [A, B] with revisions unchanged since the start, a marker within [A, B] advances to B+1; a marker before A stays; days after B remain stale until processed.

**Dirty marker caution:** If old published results are retained while stale, Portfolio query responses must include validity metadata. A single `valuation_dirty_from` may overinvalidate; later introduce asset/date-granular dependencies if needed. Clearing markers must account for any still-unprocessed dirty dates and queued work.

## HTTP endpoints

- `POST /trades`, `DELETE /trades/{id}`, `GET /trades`
- `POST /cash-movements`, `DELETE /cash-movements/{id}`, `GET /cash-movements`
- `POST /reference-prices`, `GET /reference-prices`, `DELETE /reference-prices/{id}` (audit-preserving removal)
- `GET /portfolio/positions?date=YYYY-MM-DD`, `GET /portfolio/summary?date=YYYY-MM-DD`, `GET /portfolio/pnl?start_date=&end_date=` (the published `portfolio_metrics` series: per date `cumulative_pnl`, `daily_pnl`, statuses and stale flag; feeds the Carteira cumulative chart, no per-asset data; OQ-16)
- `POST /processing/requests`, `GET /processing/requests`, `GET /processing/requests/{id}`, `POST /processing/requests/{id}/cancel`, `POST /processing/requests/{id}/cancel-and-replace`
- `GET /instruments`, `POST /instruments`, `GET /products`, `POST /products`; direct `POST /pricing/calculate` for previews if needed (the current UI shows no preview: the complementary PU or rate is computed when an entry is saved, OQ-19).
- **UI read needs (OQ-19, OQ-20).** The frontend's draft contract (lane I) proposes how each is served; the integrator fixes route names and shapes:
  - Pendências list: an HTTP route for `ProcessingService.get_issues`, three issue types only.
  - Range preview: an HTTP route for `ProcessingService.preview_range` (exact [A, B], number of days, stale-predecessor flag).
  - Processing request read: requested range, status, days done and total, the date being processed, created/started/finished times and the error message, if any.
  - Ativos catalogue: instrument types and asset classes, and per product its class, type and number of contracts.
  - Contract list: per instrument, its latest current reference observation `{date, pu, rate, source}`, or `null`.
  - Reference prices: the source of each observation and the revision history for an (asset, date).
  - Trades: both execution PU and execution rate.
  - Lançamentos cash strip: `GET /portfolio/summary` for the range end date and the day before, with their stale and unprocessed flags.
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
