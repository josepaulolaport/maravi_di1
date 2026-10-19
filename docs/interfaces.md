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
One table, `ledger.entries` (OQ-24): each entry is a TRADE or a CASH movement, with `entry_date`, `entry_time` (required, São Paulo local time) and one `seq` shared by both types. The order is `(entry_date, entry_time, seq)` across both types. A CASH entry stores a signed `cash_amount` (positive aporte, negative retirada, never 0); a trade's cash effect is not stored, it is computed on read as −`signed_quantity` × `execution_pu` by the single function in the portfolio cash domain.
- `LedgerService.create_entry(request, *, uow) -> LedgerEntry` (a trade or a cash movement)
- `LedgerService.delete_entries(ids, *, uow) -> None`: soft delete of one or many entries of either type, with no reason, in one transaction, all or nothing; the entries deleted together share one `deletion_batch_id` (OQ-24).
- `LedgerService.list_entries(start_date, end_date, search, order, limit, cursor) -> page of LedgerEntry`, the read behind `GET /ledger/entries` (keyset pagination on `(entry_date, entry_time, seq)`, OQ-26; method name integrator-defined).
- `LedgerReader.get_trades(start_date, end_date) -> ordered list[TradeRecord]` and `LedgerReader.get_cash_movements(start_date, end_date) -> ordered list[CashMovementRecord]` keep their names and read the active entries of `ledger.entries` of their type, in `(entry_date, entry_time, seq)` order. `CashMovementRecord` gains the time, the `seq` and the signed amount (OQ-24).
- Writes validate Asset and use Pricing when a trade is rate-only or PU-only. Validation (OQ-1, OQ-13, OQ-14, OQ-24): `entry_time` required for both types; nothing dated after today (São Paulo, injected clock); a trade may be dated up to the maturity date inclusive (on it the PU is typed and the rate stored as 0), never after; bounds are only the schema CHECKs. Execution PU/rate are stored on the immutable trade. Ledger never creates reference prices.
- Invalidation follows the type, in the same Unit of Work as the write, and never enqueues work (OQ-23 item 3): a trade calls `trades_changed` (cash and positions), a cash movement `cash_movements_changed` (cash only). A mixed batch delete invalidates each needed chain once, from its earliest date: positions from the earliest trade, cash from the earliest entry of either type (OQ-24).

### Prices
- `PriceService.set_reference_price(request, *, uow) -> ReferencePriceRecord`: one row per (asset, date, source) (OQ-25). Adding a price where the (asset, date, source) row already exists deletes the current row and inserts the new one, with a new id, in the same Unit of Work (OQ-26 item 7).
- `PriceService.correct_reference_price(..., *, uow) -> ReferencePriceRecord`: an UPDATE in place, same id, `updated_at` set.
- `PriceService.remove_reference_price(..., *, uow) -> None`: DELETEs the row; with MANUAL gone, B3 becomes preferred.
- `PriceReader.get_preferred(asset_id, reference_date) -> ReferencePriceRecord | None`
- `PriceReader.get_preferred_many(asset_ids, dates) -> mapping`
- `ReferencePriceRecord` has no `revision` (OQ-25).
- Reference prices may be dated up to the maturity date inclusive (PU typed on it, rate 0), never after it or after today (OQ-1, OQ-14). After maturity the reference PU is 0 by definition and no observation exists.
- Preferred source order: MANUAL, then B3. Exactly the requested calendar date; no carry-forward. There are no revisions: traceability is on the published row, which stores the `reference_pu` it used and its `reference_source` (OQ-25). Every set, correction and removal calls `prices_changed` in the same Unit of Work (positions stale from its date, OQ-23 item 3) but changes no quantity; it never enqueues processing. Future bulk import can call the same PriceService via a separate RabbitMQ adapter.

### Portfolio
Pure domain calculators (`portfolio/domain/`, frozen dataclasses). Two independent chains read the same Ledger facts and never each other's output (OQ-21); the application layer maps `ledger.public.TradeRecord` onto Portfolio's own `Trade(asset_id, trade_date, trade_time, seq, signed_quantity, execution_pu, execution_rate)`, ordered by `(trade_date, trade_time, seq)` (OQ-13). A skipped day or misdated event raises the internal `AccountingError`, not a `DomainError`.
- **Positions chain** (no cash, no prices): `PositionsEngine.calculate_day(previous_state: PositionState, trades, date) -> PositionsDay` and `calculate_range(previous_state, trades, end_date) -> tuple[PositionsDay, ...]`. `PositionState(as_of, positions: tuple[OpenPosition, ...])` holds `OpenPosition(asset_id, quantity ≠ 0, average_entry_pu, average_entry_rate)`; `PositionDay(asset_id, previous_quantity, quantity, average_entry_pu, average_entry_rate, trades)` exists exactly for the expected assets (OQ-10), quantity 0 included, with averages `None` when flat. Averages are rounded at each day's close (PU 10 dp, rate 12 dp, OQ-3) and carried forward as stored, so one job over [A, B] equals several jobs that read the previous day back.
- **Cash chain** (no positions, no prices): `CashCalculator.calculate_day(previous_balance: CashBalance, trades, deposits: Decimal, withdrawals: Decimal, date) -> CashDay` and `calculate_range(previous_balance, trades, deposits: Mapping[date, Decimal], withdrawals: Mapping[date, Decimal], end_date) -> tuple[CashDay, ...]`. `deposits`/`withdrawals` are the day's totals, summed by the application from `LedgerReader.get_cash_movements` (`0` when none, never negative; a date absent from the maps means none). `CashDay(date, previous_cash_balance, trades_cash_flow, deposits, withdrawals, cash_balance)` with `trades_cash_flow = −Σ(signed_qty × execution_PU)`: one `cash_balances` row.
- **Valuation**: `ValuationCalculator.calculate_day(date, assets: Sequence[AssetValuationInput], cash_balance: Decimal | None) -> PortfolioValuation`. `AssetValuationInput(asset_id, quantity, maturity_date, reference_pu, reference_source)`: a PU and its source (MANUAL or B3) go together or not at all (OQ-9, OQ-25); past maturity the caller passes neither. Per asset `AssetValuation(asset_id, reference_pu, reference_source, financial_total = Q × reference_PU, status)` with `status` COMPLETE, MISSING or NOT_REQUIRED: Q ≠ 0 without a price is MISSING and `null`; Q = 0 is worth 0, NOT_REQUIRED; after maturity the PU is 0 by definition, COMPLETE, with no source (OQ-1). `PortfolioValuation(date, assets, positions_market_value, aum, status)`: the market value is `null` if any asset is MISSING (never a partial sum), and AUM = cash + market value, `null` when either side is missing. No multiplier (OQ-2).
- `PortfolioAccounting.calculate_day(previous_state: AccountingState, trades, deposits, withdrawals, date) -> AccountingDay(cash: CashDay, positions_day: PositionsDay)` and `calculate_range(previous_state, trades, deposits: Mapping[date, Decimal], withdrawals: Mapping[date, Decimal], end_date) -> tuple[AccountingDay, ...]` run both chains over the same days, for an ALL scope only; `AccountingState(as_of, cash_balance, positions)`.
- Predecessor readers, one per chain (OQ-21, OQ-22): `PortfolioReader.get_previous_positions(before_date)` → the `PositionState` published for `before_date − 1`, or none; `get_previous_cash(before_date)` → the `CashBalance` from the published `cash_balances` row of `before_date − 1`, or none. A POSITIONS job reads only the first, a CASH job only the second, an ALL job both. Whether that predecessor is current is not a Portfolio flag: Processing reads it from `date_status` (OQ-23).
- `PortfolioReader.get_positions(date) -> list[Position]`
- `PortfolioQueryService.get_position_table(date) -> PositionTableView`
- `PortfolioQueryService.get_summary(date) -> PortfolioSummaryView`
- `PortfolioResultsWriter` writes one date at a time, inside that date's transaction (OQ-23): `write_positions_day(PositionsDay, asset_metrics, portfolio_metrics, *, uow)` for POSITIONS and `write_cash_day(CashDay, *, uow)` for CASH; ALL calls both in the same transaction. Each upserts the date's published rows and recomputes that date's `aum` from the other chain's published value (OQ-21). There is no staging and no `publish_range` (OQ-23); Processing calls these through `public.py` and sets the date's status in the same transaction.
- Portfolio owns published `positions`, `position_metrics`, `portfolio_metrics` and `cash_balances` (OQ-8); daily quantities and average costs remain calculable with missing reference prices. AUM = cash (`cash_balances`) + sum signed position market values (`portfolio_metrics`), `null` when either side is missing, stale when either chain is stale on that date in `date_status`. No exposure or `total_equity` fields. Rows exist for D exactly for expected assets: Q[D−1] ≠ 0 or a trade on D, including quantity 0 (OQ-10). `position_metrics` stores the `reference_pu` used and its `reference_source` (MANUAL or B3; NULL with no price or after maturity) instead of a `reference_price_id`; the D−1 reference PU is read from D−1's row (OQ-9, OQ-25). Read models report each date's cash and positions statuses from `date_status` (OQ-23). Published read models join documented read surfaces by date and asset; never recombine latest Prices observations with older P&L.

### PnL
- `AssetPnLCalculator.calculate(previous_position, day_trades, previous_reference_pu, current_reference_pu) -> AssetPnLResult`
- `PortfolioPnLCalculator.aggregate(expected_assets, asset_results, previous_cumulative) -> PortfolioPnLResult`
- Pure functions; no persistence or messaging adapters required initially.
- First day: when Q[D−1] = 0, `position_pnl` is exactly 0 and needs no D−1 price (OQ-4). After maturity the current reference PU is 0 (OQ-1). Precision: 34-digit `Decimal`, `ROUND_HALF_UP` (OQ-3). The multiplier is not applied (OQ-2).
- P&L uses daily Position P&L + Trades P&L attribution; deposits/withdrawals do not enter P&L. Missing required price => incomplete/null P&L, never silently zero or sum just available assets. Cumulative chain unavailable after an unresolved gap.

### Processing
- `FinancialResultInvalidator.trades_changed(effective_date, *, uow)` (cash and positions), `cash_movements_changed(effective_date, *, uow)` (cash only) and `prices_changed(asset_id, reference_date, *, uow)` (positions only: valuation and P&L) (OQ-21). Each sets the affected chain columns of `processing.date_status` to `STALE` on every date ≥ the given date that already has a status, in the caller's Unit of Work, without committing; dates without a status stay not processed (OQ-23). A chain that is `RUNNING` on a date keeps `RUNNING`; its kept previous status becomes `STALE` only when there is one (a date never processed before has none and stays not processed after a restore) (OQ-26). It locks those rows in ascending date order (`SELECT … ORDER BY date FOR UPDATE`) before updating them, the same order the run uses, so the two never deadlock. There are no revision counters and no dirty markers.
- `processing.date_status(date, portfolio, cash, portfolio_previous, cash_previous)` is the single source of freshness (OQ-23); the `*_previous` columns hold a chain's status while it is `RUNNING`, so it can be put back (OQ-26): per date and chain, NULL or no row = not processed (Não processado), `FRESH` (Atualizado), `FRESH_WITH_ISSUES` (Atualizado com pendências), `STALE` (Desatualizado), `RUNNING` (Processando), `FAILED` (Erro; the date keeps its previously published data). Processing exposes a read of it for a date or a range through `public.py`, for Portfolio's read models (name and shape to be specified).
- `ProcessingService.preview_range(scope, start_date, end_date) -> ProcessingPreview` — the range is exactly [start, end] (OQ-11); the preview reports, per chain of the scope, the `date_status` of start−1 and warns when it is not `FRESH` or `FRESH_WITH_ISSUES`. `scope` ∈ {CASH, POSITIONS, ALL} (OQ-21).
- `ProcessingService.enqueue_range(scope, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.request_cancel(request_id, *, uow) -> ProcessingRequest`
- `ProcessingService.cancel_and_replace(active_id, scope, start_date, end_date, *, uow) -> ProcessingRequest`
- `ProcessingService.list_requests(limit, cursor)` (keyset pagination on `(created_at, id)`), `get_request(id)`, `get_issues(...)`
- `ProcessingRequest` is the run, one row of `processing.requests` (OQ-23): `id`, `scope`, `start_date`, `end_date`, `status` (eight statuses, no `SUPERSEDED`), `progress_date` (the last date the run committed), `error_code`, `error_message`, `created_at`, `updated_at`, `dispatched_at`, `started_at`, `finished_at`, `cancel_requested_at`. Days done and total derive from the range and `progress_date`. Claim token and lease stay inside Processing.
- `ProcessingDispatcher.dispatch_next() -> Optional[request_id]`: transactionally claim singleton `calculation_state` row, set job DISPATCHED, record outbox command.
- `PortfolioRangeProcessor.run(request_id, claim_token)`: claim/lease (60 s, renewed per date, OQ-5); process exactly the requested dates (OQ-11), in calendar order, from `start_date`, or from the day after `progress_date` on recovery. For each date D, for the chains of the scope (OQ-23):
  1. a short transaction, under a row lock on the run's `processing.requests` row that checks the claim token and lease, keeps the chain's status on D in `*_previous` and sets it to `RUNNING` (both chains for ALL); a date with no row gets one with `*_previous` NULL; a chain already `RUNNING` (recovery) keeps its `*_previous` untouched;
  2. D's transaction locks the run's `requests` row (claim token and lease checked) and the `date_status` rows of D−1 and D in ascending date order, computes D (CASH: `CashCalculator`; POSITIONS: `PositionsEngine`, Prices, `ValuationCalculator`, PnL; ALL: both), writes D through `PortfolioResultsWriter` (which recomputes D's AUM), replaces the chain's issues for D (deletes the earlier ones of that chain and date — positions: `chain = 'POSITIONS'` plus `MISSING_REFERENCE_PRICE` and `EXPIRED_OPEN_POSITION`, whose `chain` is NULL; cash: `chain = 'CASH'` — and writes the new ones, OQ-26), sets `requests.progress_date = D`, sets D's status by the predecessor rule below, and commits. For ALL both chains and the AUM of D are in this one transaction.
  - **Status of D:** when D−1 is `FRESH` or `FRESH_WITH_ISSUES`, or is the chain's zero state (positions: no active TRADE dated on or before D−1; cash: no active entry of either type, OQ-22, OQ-26), D is `FRESH`, or `FRESH_WITH_ISSUES` when D has a missing price or an expired open position; when D−1 is anything else, D is `STALE` with a `STALE_PREDECESSOR` issue naming the chain, and positions have `pnl_status = MISSING` (OQ-11, OQ-22).
  - A write landing during the run waits on those row locks, then marks what it affects `STALE`; the run never stops for it.
  - **Failure at D:** D's transaction rolls back; a short transaction, fenced by the claim token like every worker write, sets the chain's status on D to `FAILED` (clearing `*_previous`) and stores `error_code` and `error_message` on the run, which ends `FAILED`. Later dates are not touched.
  - **A date left `RUNNING`:** whenever a run ends without committing a date it set `RUNNING` (cancel, or finalization after a lost lease; a failure at D sets D `FAILED` instead), that date's chain status is restored from `*_previous`; if that leaves both chains of the date without a status, the row is deleted (OQ-26).
  - Every worker write — `RUNNING`, the date's transaction, `FAILED`, the run's error and end status — checks the claim token and lease under a row lock on the run's `requests` row, in the same transaction, so a fenced-out worker changes nothing.
  - **End:** `COMPLETED`, or `COMPLETED_WITH_ISSUES` when a date it wrote is `FRESH_WITH_ISSUES` or `STALE`.
  - No nested RabbitMQ message per asset or per day.
- Issue types: `MISSING_REFERENCE_PRICE`, `EXPIRED_OPEN_POSITION`, `STALE_PREDECESSOR`; a `STALE_PREDECESSOR` names its chain (`CASH` or `POSITIONS`, OQ-22).
- Cash predecessor rule (OQ-22): a CASH or ALL job whose start−1 has no published cash while an active trade or cash movement is dated on or before start−1 publishes nothing and ends `FAILED` with `error_code = CASH_PREDECESSOR_MISSING`; stale cash at start−1 runs and its dates are `STALE`. Checked when the job starts; enqueueing is never refused for it.
- Cancellation of queued work is immediate. A running cancellation sets `cancel_requested_at`; the worker checks it between dates: the current date commits, later dates are not touched, and the run ends `CANCELLED`. A cancel that arrives during the last date lets the run end `COMPLETED`, or `COMPLETED_WITH_ISSUES` when a date it wrote has issues (OQ-23, OQ-26). Overlapping requests allowed in PostgreSQL, one active global job.

## Transaction boundaries and behavior

1. **Mutation:** HTTP handler opens UoW; Ledger or Prices writes the authoritative record; the Processing invalidator locks, in ascending date order, and sets the affected chains `STALE` in `date_status` on the dates ≥ the write's date that have a status, in the same session (waiting on the row locks of a date being processed); one COMMIT; return response. No automatic processing job.
2. **Enqueue:** HTTP handler opens UoW; Processing validates requested dates; insert `requests(status=QUEUED)`; COMMIT; return job ID. Do not publish one Rabbit message per enqueued job.
3. **Dispatch:** dispatcher under row lock selects oldest eligible QUEUED request by (created_at, id), sets singleton active ID and DISPATCHED, saves outbox command in same transaction, COMMIT. Outbox relay publishes with confirms.
4. **Execute, one date per transaction (OQ-23):** worker claims the specific dispatched job using claim token and time-bounded lease. For each date: a short transaction sets the date's chain status `RUNNING`; then the date's transaction locks the run's `requests` row and the `date_status` rows of D−1 and D in ascending date order, verifies the claim token and lease, upserts D's published rows and AUM, sets D's status and `requests.progress_date`, and commits. There is no staging and no range-wide publish. Processing controls transaction durations; calculators have no DB side effects.
5. **Cancel:** request cancel flag committed; worker checks it between dates; the current date commits, later dates are not touched, the run ends `CANCELLED`; queued jobs are cancelled before dispatch.
6. **Failure and recovery:** a failing date's transaction rolls back; a short transaction sets that date `FAILED` and stores the error on the run, which ends `FAILED`; later dates are not touched and earlier ones stay published. After a crash or a lost lease, recovery is explicit and resumes after `requests.progress_date`; the claim token stops a fenced-out worker from committing a date.
7. **Broker semantics:** RabbitMQ delivery at-least-once. Inbox idempotency plus request/status/claim fencing guards duplicate delivery. ACK only after durable state transition. Retries transient only; domain missing prices are `COMPLETED_WITH_ISSUES`, not retries. Relay and dispatcher recover after crashes.

**Freshness rule (OQ-23):** `processing.date_status` is the only source of freshness; there are no dirty markers and no revision counters. Every Portfolio read reports, for each date, the cash and positions statuses from it (no row = not processed). A write marks only dates that already have a status; dates after a processed range stay not processed until they are processed.

## HTTP endpoints

Paginated lists take `?limit=&cursor=` and return `{items, next_cursor}`, with keyset cursors: `(entry_date, entry_time, seq)` for ledger entries and `(created_at, id)` for processing requests (OQ-26).

- `GET /ledger/entries?start_date=&end_date=&search=&order=&limit=&cursor=` (paginated, both types), `POST /ledger/entries` (a trade or a cash movement), `POST /ledger/entries/deletions` with `{ids}` (soft delete in one transaction, all or nothing, one `deletion_batch_id`) (OQ-24). They replace `/trades` and `/cash-movements`. A trade item may expose its computed cash effect as `cash_amount`.
- `POST /reference-prices` (adds a price; an existing one for the same asset, date and source is deleted first, OQ-26 item 7; this is how the UI's Corrigir works), `GET /reference-prices`, `DELETE /reference-prices/{id}` (deletes the row, OQ-25). The HTTP shapes are those of the frontend contract in PR #41 (`frontend/src/api/contract/*`), with the corrections agreed with lane I (OQ-26 item 8)
- `GET /portfolio/positions?date=YYYY-MM-DD`, `GET /portfolio/summary?date=YYYY-MM-DD`, `GET /portfolio/pnl?start_date=&end_date=` (the published `portfolio_metrics` series: per date `cumulative_pnl`, `daily_pnl`, statuses and the `date_status` of the date; feeds the Carteira cumulative chart, no per-asset data; OQ-16). Each portfolio read carries the date's cash and positions statuses from `date_status` (OQ-23).
- `POST /processing/requests`, `GET /processing/requests` (paginated), `GET /processing/requests/{id}`, `POST /processing/requests/{id}/cancel`, `POST /processing/requests/{id}/cancel-and-replace`
- `GET /instruments`, `POST /instruments`, `GET /products`, `POST /products`; direct `POST /pricing/calculate` for previews if needed (the current UI shows no preview: the complementary PU or rate is computed when an entry is saved, OQ-19).
- **UI read needs (OQ-19, OQ-20).** The frontend's draft contract (lane I) proposes how each is served; the integrator fixes route names and shapes:
  - Pendências list: an HTTP route for `ProcessingService.get_issues`, three issue types only.
  - Range preview: an HTTP route for `ProcessingService.preview_range` (scope, exact [A, B], number of days, and per chain of the scope the `date_status` of start−1; a missing cash start−1 warns that the job will end `CASH_PREDECESSOR_MISSING`; OQ-21, OQ-22, OQ-23).
  - Processing request read: `id`, `scope`, `start_date`, `end_date`, status (eight, no `SUPERSEDED`), `progress_date` (days done and total derive from it and the range), created/started/finished/updated times, `error_code` and `error_message`, if any (OQ-23). "Solicitar novo processamento" prefills from the failed date, or, for a cancelled run, from the first date it did not reach, to the original end.
  - Ativos catalogue: instrument types and asset classes, and per product its class, type and number of contracts.
  - Contract list: per instrument, its latest reference observation `{date, pu, rate, source}`, or `null`.
  - Reference prices: the source of each observation; there is no revision history (OQ-25).
  - Ledger entries: each trade with both execution PU and execution rate.
  - Lançamentos cash strip: `GET /portfolio/summary` for the range end date and the day before; the cash comes from `cash_balances`, with the date's cash status from `date_status` (OQ-21, OQ-23).
  - Processing scope: the request form and list carry `scope` (CASH, POSITIONS, ALL; UI labels Caixa, Posições, Tudo), and the summary reports the date's cash and positions statuses separately, from `date_status` (OQ-21, OQ-23).
- All UI-facing content/labels in pt-BR; schema, internal interfaces, and Python identifiers remain English.

### Errors (OQ-15)

Every error response is RFC 9457 `application/problem+json`:

```json
{"type": "about:blank", "title": "…", "status": 422, "detail": "…",
 "errors": [{"code": "FUTURE_DATE", "message": "A data não pode ser posterior a hoje.", "field": "entry_date"}]}
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
4. Processing requests, `date_status`, dispatch/outbox/inbox, cancellation, per-date publication and recovery from `progress_date` (OQ-23).
5. Integration tests for competing overlapping requests, cancel and replace, crashes, writes landing during a run, failure at a date, missing prices, weekend handling, 365-day pricing.
6. Future TODO (not part of challenge MVP): asynchronous CSV/B3 ingestion via same Prices service.

**Decided on 2026-10-18** (see `open-questions.md`): maturity (OQ-1), multiplier (OQ-2), precision (OQ-3). **Still not invented:** external official-price ingestion (post-delivery TODO).
