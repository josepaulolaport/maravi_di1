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
- `PricingService.calculate(instrument: InstrumentDescriptor, reference_date, input: PricingInput) -> PricingResult`
- `PricingInput` has exactly one authoritative input: rate or PU. `PricingResult` returns PU, rate where derivable, methodology (`CHALLENGE_DC_365`), version, input_kind.
- `DI1Calculator` is pure and returns a value. Calculators never publish messages or persist results. `PriceService` and `LedgerService` can both call Pricing's public interface; P&L does **not** belong here.

### Ledger
- `LedgerService.create_trade(request, *, uow) -> Trade`
- `LedgerService.delete_trade(trade_id, reason, *, uow) -> None` (soft delete)
- `LedgerService.create_cash_movement(request, *, uow) -> CashMovement`
- `LedgerService.delete_cash_movement(id, reason, *, uow) -> None`
- `LedgerReader.get_trades(start_date, end_date) -> ordered list[Trade]`
- `LedgerReader.get_cash_movements(start_date, end_date) -> ordered list[CashMovement]`
- Writes validate Asset and use Pricing when entry is rate-only or PU-only. Execution PU/rate are stored on the immutable trade. Ledger never creates reference prices. Input writes synchronously invalidate accounting from effective date in the same DB transaction, but never enqueue P&L work.

### Prices
- `PriceService.set_reference_price(request, *, uow) -> ReferencePrice`
- `PriceService.supersede_reference_price(...) -> ReferencePrice` (new revision, never overwrite economic values)
- `PriceService.remove_current_reference_price(...)` (supersede/remove availability according to audit policy)
- `PriceReader.get_preferred(asset_id, reference_date) -> ReferencePrice | None`
- `PriceReader.get_preferred_many(asset_ids, dates) -> mapping`
- Preferred current source order: MANUAL, then B3. Exactly the requested calendar date; no carry-forward. One current observation per (asset, date, source), superseded rows retained. Reference price IDs are returned to consumers for reproducibility. Price writes invalidate valuation/P&L dependencies but not quantities, in the same transaction; never automatically enqueue processing. Future bulk import can call the same PriceService via a separate RabbitMQ adapter.

### Portfolio
- `PortfolioAccounting.calculate_day(previous_state, trades, cash_movements, date) -> AccountingDay`
- `PortfolioReader.get_previous_valid_accounting_state(before_date) -> AccountingState`
- `PortfolioReader.get_positions(date) -> list[Position]`
- `PortfolioQueryService.get_position_table(date) -> PositionTableView`
- `PortfolioQueryService.get_summary(date) -> PortfolioSummaryView`
- `PortfolioResultsWriter.stage_day(request_id, AccountingDay, asset_metrics, portfolio_metrics, *, uow)` and `publish_range(request_id, effective_range, *, uow)`
- Portfolio owns published `positions`, `position_metrics`, `portfolio_metrics` and their staging representations; daily quantities and average costs remain calculable with missing reference prices. AUM = cash + sum signed position market values, nullable when required prices missing. No exposure or `total_equity` fields. Published read models join documented read surfaces by date and asset; never recombine latest Prices observations with older P&L.

### PnL
- `AssetPnLCalculator.calculate(previous_position, day_trades, previous_reference_pu, current_reference_pu) -> AssetPnLResult`
- `PortfolioPnLCalculator.aggregate(expected_assets, asset_results, previous_cumulative) -> PortfolioPnLResult`
- Pure functions; no persistence or messaging adapters required initially.
- P&L uses daily Position P&L + Trades P&L attribution; deposits/withdrawals do not enter P&L. Missing required price => incomplete/null P&L, never silently zero or sum just available assets. Cumulative chain unavailable after an unresolved gap.

### Processing
- `FinancialResultInvalidator.ledger_changed(effective_date, *, uow)` and `prices_changed(asset_id, reference_date, *, uow)`
- `ProcessingService.preview_range(start_date, end_date) -> ProcessingPreview`
- `ProcessingService.enqueue_range(start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.request_cancel(request_id, *, uow) -> ProcessingRequest`
- `ProcessingService.cancel_and_replace(active_id, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.list_requests()`, `get_request(id)`, `get_issues(...)`
- `ProcessingDispatcher.dispatch_next() -> Optional[request_id]`: transactionally claim singleton `calculation_state` row, set job DISPATCHED, record outbox command.
- `PortfolioRangeProcessor.run(request_id, claim_token)`: claim/lease, resolve effective dates and latest input revisions, loop one calendar day at a time, calculate Portfolio accounting, retrieve Prices, calculate PnL, stage results/progress; check cancellation between dates and before publication; publish only with matching input revisions and active fencing token; then finish job. No nested RabbitMQ message per asset or per day.
- Cancellation of queued work is immediate. Running cancellation sets a request marker; worker stops safely and discards staged data. Overlapping requests allowed in PostgreSQL, one active global job.

## Transaction boundaries and behavior

1. **Mutation:** HTTP handler opens UoW; Ledger or Prices writes authoritative record; Processing invalidator updates revision/dirty metadata using same session; one COMMIT; return response. No automatic processing job.
2. **Enqueue:** HTTP handler opens UoW; Processing validates requested dates; insert `requests(status=QUEUED)`; COMMIT; return job ID. Do not publish one Rabbit message per enqueued job.
3. **Dispatch:** dispatcher under row lock selects oldest eligible QUEUED request by (created_at, id), sets singleton active ID and DISPATCHED, saves outbox command in same transaction, COMMIT. Outbox relay publishes with confirms.
4. **Execute:** worker claims specific dispatched job using claim token and time-bounded lease, starts from latest committed inputs, iterates by calendar date and saves run-scoped staged rows. Processing controls transaction durations; calculators have no DB side effects.
5. **Cancel:** request cancel flag committed, worker checks between date commits; cancel queued jobs before dispatch; cancelled run's staging is discarded. A crash/timeout lease recovery is explicit.
6. **Publish:** transaction obtains processing singleton lock, verifies claim token/cancellation and relevant input revisions, atomically upserts published positions and both metrics tables for the effective range, replaces stale dated rows where necessary, updates dirty status carefully, and marks job complete or with issues. On source revision mismatch, discard staging and mark SUPERSEDED. Make outputs visible together.
7. **Broker semantics:** RabbitMQ delivery at-least-once. Inbox idempotency plus request/status/claim fencing guards duplicate delivery. ACK only after durable state transition. Retries transient only; domain missing prices are `COMPLETED_WITH_ISSUES`, not retries. Relay and dispatcher recover after crashes.

**Dirty marker caution:** If old published results are retained while stale, Portfolio query responses must include validity metadata. A single `valuation_dirty_from` may overinvalidate; later introduce asset/date-granular dependencies if needed. Clearing markers must account for any still-unprocessed dirty dates and queued work.

## HTTP endpoints

- `POST /trades`, `DELETE /trades/{id}`, `GET /trades`
- `POST /cash-movements`, `DELETE /cash-movements/{id}`, `GET /cash-movements`
- `POST /reference-prices`, `GET /reference-prices`, `DELETE /reference-prices/{id}` (audit-preserving removal)
- `GET /portfolio/positions?date=YYYY-MM-DD`, `GET /portfolio/summary?date=YYYY-MM-DD`, `GET /portfolio/pnl?start_date=&end_date=`
- `POST /processing/requests`, `GET /processing/requests`, `GET /processing/requests/{id}`, `POST /processing/requests/{id}/cancel`, `POST /processing/requests/{id}/cancel-and-replace`
- `GET /instruments`, `POST /instruments`, `GET /products`, `POST /products`; direct `POST /pricing/calculate` for previews if needed.
- All UI-facing content/labels in pt-BR; schema, internal interfaces, and Python identifiers remain English.

## DI composition

`modules/<name>/public.py` exposes stable read/service contracts and DTOs; `modules/<name>/dependencies.py` creates module-local implementations; `composition/dependencies.py` wires cross-module collaborators and UoW; `composition/routers.py` registers routes; `composition/consumers.py` registers handlers; workers use plain factories, not FastAPI `Depends`. No one-class-per-command framework; cohesive application services.

## Implementation/verification order

1. Asset, Pricing, Ledger and Prices; Decimal calculations and immutable inputs with synchronous invalidation.
2. Portfolio accounting state and PnL pure calculators; exact-date missing price rules, reversal tests.
3. Portfolio published tables and one-query consolidated frontend read models.
4. Processing requests, staging, dispatch/outbox/inbox, cancellation and publication/revision fencing.
5. Integration tests for competing overlapping requests, cancel and replace, crashes, stale publishes, missing prices, weekend handling, 365-day pricing.
6. Future TODO (not part of challenge MVP): asynchronous CSV/B3 ingestion via same Prices service.

**Unresolved, intentionally not invented:** exact maturity settlement cash treatment and multiplier economics, external official-price ingestion, precision/rounding rules beyond Decimal discipline. Those must be explicit before their code path is implemented.
