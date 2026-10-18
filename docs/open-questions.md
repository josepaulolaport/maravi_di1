# Open questions

Status: 2026-10-18. These are decisions the specs leave open, or points where the specs disagree with each other. **Only the user answers them.** Code that depends on an open question is not written: it stops with a `spec-gap` (see `.claude/skills/spec-gap`).

When the user answers a question, its answer moves to the "Closed" list in `maravi_business_specification.md` §14, and the question is moved to "Answered" below.

## Open, from the specs themselves

These questions come from business spec §14 ("Aberto"), implementation plan §11, schema.md and interfaces.md.

| ID | Question | Blocks |
|---|---|---|
| OQ-1 | **Maturity settlement.** What is the settlement event, its effect on cash and position, its date convention, and what happens to a contract that matures with an open position? | Portfolio accounting after maturity; see also OQ-6 |
| OQ-2 | **Multiplier and notional.** Does `asset.futures.contract_multiplier` enter cash, market value and P&L, and how? Today the formulas use the PU directly. | Ledger cash effect, Portfolio, PnL |
| OQ-3 | **Precision and rounding.** Internal and stored scales and the rounding method, especially at the price limits and in the PU → rate inversion. | Pricing (Wave 1 B), Wave 0 freeze |
| OQ-4 | **The first P&L day** when there is no previous PU: what P&L is available? | PnL |
| OQ-5 | **Operational limits.** The maximum range size, how long jobs and staging rows are kept, queue priorities, and the timeout/lease values. | Processing (Wave 4) |
| OQ-7 | **Zero days to maturity and non-business dates.** What does the PU ↔ rate inverse do on the maturity day? Are entries on weekends and holidays accepted? (plan §11.4) | Pricing, Ledger validation |

## Open, found when the old docs were replaced (2026-10-18)

| ID | Question | Where the specs disagree or are silent |
|---|---|---|
| OQ-6 | **A contract held past maturity can never be priced again.** Under the exact-date rule (spec §5) it stays `MISSING`, and the cumulative P&L chain breaks for good (spec §8.3). This depends on OQ-1. | spec §5, §8.3, §14 item 1 |
| OQ-8 | **Who owns the staging tables?** `interfaces.md` (Portfolio) says Portfolio owns the staging representations. `schema.sql` puts `staged_*` in the `processing` schema. Plan §6 leaves this "for X to resolve". | interfaces.md Portfolio; schema.sql; plan §6 |
| OQ-9 | **Tracing the D−1 price.** `position_pnl` uses the reference PU of D−1, but `position_metrics.reference_price_id` links only the price of D. Spec §5 requires that the price used can be traced. | spec §5, §8.1; schema.sql `position_metrics` |
| OQ-10 | **"Expected assets", and when a `positions` row with quantity 0 is written.** The portfolio P&L is complete only if every expected asset has a result (spec §8.3), but the term is not defined. The implied rule is: Q[D−1] ≠ 0, or a trade on D. Every `position_metrics` row needs a `positions` row (FK). | spec §8.3; schema.md invariants |
| OQ-11 | **How far the effective range expands.** Spec §10.1 says the range is "expanded to reach a valid predecessor state". From which marker (`accounting_dirty_from`, `valuation_dirty_from`, the last published day), and how far back for the cumulative P&L? | spec §10.1; interfaces.md Processing |
| OQ-12 | **Clearing the dirty markers.** There is a single `valuation_dirty_from` date. When can a job clear it while other dirty dates are unprocessed or still queued? (interfaces.md "Dirty marker caution") | interfaces.md; schema.sql `calculation_state` |
| OQ-13 | **Trade time and order.** The spec says "data/hora efetiva". The schema has `trade_date` plus an optional `trade_time TIME` with no timezone. Where do trades with `NULL` time sort? (plan §3: "NULLS policy") | spec §6.1; schema.sql `ledger.trades`; plan §3 |
| OQ-14 | **Validation rules.** What are the rate and PU bounds, the maturity limits, and the rule for future-dated entries? Can a trade or price be dated on or after maturity? | spec §4, §6; nothing in the specs |
| OQ-15 | **The error contract.** What is the error response shape and its codes, for the frontend and the MSW mocks? | spec §12; interfaces.md HTTP |
| OQ-16 | **`GET /portfolio/pnl?start_date=&end_date=`** appears only in `interfaces.md`. Is it the source of the cumulative P&L chart (spec §11.4)? What is its response? | interfaces.md HTTP; spec §11.4 |
| OQ-17 | **Who owns `platform/**`?** Plan §2 prose says the integrator is "the only editor of … `platform` shared code". Plan §2 table gives `platform/**` to lane H. | plan §2 |
| OQ-18 | **Discrepancies with the challenge.** Spec header: discrepancies with the challenge "must be recorded and not hidden". The old docs read challenge §5 ("preços de referência disponíveis") as "the latest price on or before D". Exact-date only is a different reading, and it needs a line in the README. Are there others to record (e.g. settlement)? | spec header, §5 |

## Answered

None yet.
