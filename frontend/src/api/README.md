# API layer (draft contract)

- `contract/`: response and request types. snake_case names follow `docs/schema.sql`; decimals are strings; `null` means unavailable.
- `http.ts`: the only HTTP client. JSON in and out; RFC 9457 problem+json errors become `ApiError` (OQ-15).
- `endpoints.ts`: one typed function per endpoint. Feature hooks call these.
- `mocks/`: the MSW fake backend: a stateful in-memory store (`db.ts`) seeded from one coherent scenario (`fixtures.ts`), with the documented validations, dirty markers and a job that advances one step per poll.

At Wave 5 the hand-written types are replaced by types generated from the backend's OpenAPI (`npm run gen:api`).

## Contract proposals for the integrator

Everything below is used by the frontend but not yet named in `docs/interfaces.md` or `docs/schema.sql`.

| #   | Proposal                                                                                                                                                          | Why                                                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| P1  | API served under `/api` (`VITE_API_BASE_URL`)                                                                                                                     | SPA routes and API paths never collide; one proxy rule                           |
| P2  | Lists wrapped as `{ items: [...] }`                                                                                                                               | Metadata can be added without a breaking change                                  |
| P3  | `GET /instrument-types` with nested `asset_classes`                                                                                                               | Ativos catalogue tabs (OQ-19 item 4)                                             |
| P4  | `Product.asset_class`, `instrument_type`, `instrument_count`; `GET /products/{id}`; `FuturesSpec.pricing_methodology`                                             | Catalogue row, product page ("Contagem de dias")                                 |
| P5  | `Instrument.product_code`, `last_reference {reference_date, pu, rate, source}`                                                                                    | Contract list, always with its date (OQ-19 item 5)                               |
| P6  | `Trade.asset_code`, `instrument_type_code`, `cash_amount` (= −q × PU, computed by the backend)                                                                    | Lançamentos table; the browser never multiplies money                            |
| P7  | `POST /ledger/deletions {trade_ids, cash_movement_ids, reason?}`, all or nothing                                                                                  | Atomic multiple delete (§6.1)                                                    |
| P8  | `GET /reference-prices` returns per date `{reference_date, preferred, current[]}`; `GET /reference-prices/revisions?asset_id&reference_date`                      | MANUAL > B3 applied by the backend; Fonte column and Ver revisões (OQ-19 item 6) |
| P9  | Portfolio responses carry `publication: 'NOT_PROCESSED' \| 'PUBLISHED'`, `stale`, `published_at`                                                                  | Unprocessed vs stale vs valid (§8.3, D3)                                         |
| P10 | `PositionRow.asset_code`, `maturity_date`, `reference_source`, `reference_rate`                                                                                   | Positions table columns (§11.4)                                                  |
| P11 | `PnlPoint.stale`                                                                                                                                                  | Chart draws only complete, non-stale points (OQ-16)                              |
| P12 | `GET /processing/preview?start_date&end_date` → `{total_days, predecessor_date, predecessor_state}`                                                               | Range preview and stale warning (OQ-11)                                          |
| P13 | `GET /processing/issues` (current, deduplicated)                                                                                                                  | Pendências list (§10.3)                                                          |
| P14 | `POST …/cancel-and-replace` returns `{cancelled, replacement}` with 201                                                                                           | Both results in one response                                                     |
| P15 | `GET /instruments/{id}`                                                                                                                                           | Contract page                                                                    |
| P16 | Query filters: `start_date`, `end_date`, `search` on `/trades` and `/cash-movements`; `product_id`, `instrument_type`, `search` on `/products` and `/instruments` | Inclusive range and search (§11.3), catalogue browsing (§11.2)                   |
| P17 | `Issue.asset_code`                                                                                                                                                | Pendências list without a second request                                         |

## Decided gap

- **GAP-I-1** (user, 2026-10-18: "go with your recommendation (date only)"): the Lançamentos design shows a time for cash movements ("17/10/2026 11:15 Aporte"), but `ledger.cash_movements` has only `movement_date`. Decision: no schema change; aportes and retiradas show the date alone. Cash effects are daily, and the accounting does not depend on the intraday order of movements.
