---
name: tdd
description: Implement or change a Maravi DI1 rule test-first — pricing (DC/365), accounting (signed positions, average PU/rate, reversals, cash), P&L attribution and aggregation, completeness, price selection, processing state transitions. Use whenever behaviour is added or changed in any module.
---

# Test-first

## 1. Pin down the rule

- Find the rule in `docs/maravi_business_specification.md`:
  - §4: pricing;
  - §5: prices;
  - §6: ledger;
  - §7: accounting;
  - §8: P&L and completeness;
  - §10: processing.
- Find the contract that applies in `docs/interfaces.md` and the deliverables of your wave in the plan.
- Write the rule in one sentence in the test module's docstring, with its references, e.g. `spec §7.2; interfaces Portfolio`.
- **If the docs do not fully determine the result, or the rule touches an OQ in `docs/open-questions.md`, stop and use `spec-gap`.**

## 2. Write the failing tests

Start from the spec §13 cases for your module. Then add:

- **The formula's documented examples:** exact inputs, with expected values as `Decimal("…")` strings computed independently from the formula (by hand or with Python `decimal`), never by running your code.
- **Boundaries:**
  - the day count;
  - a partial close and a full close;
  - crossing zero;
  - a short position;
  - several trades on the same day, in order;
  - a round trip within one day;
  - a weekend;
  - a missing price for D or for D−1;
  - a flat position.
- **Errors:** assert the error type and its meaning.
- **Invariants (property tests), where the spec states one:**
  - PU → rate → PU round trip;
  - daily P&L = position P&L + trades P&L;
  - AUM = cash + Σ market value;
  - quantity = Σ signed trades;
  - P&L never changes cash.

Run them, and **see them fail for the right reason**.

## 3. Implement

- Calculators are pure functions or frozen dataclasses: no DB, broker, clock or FastAPI.
- Use `Decimal` built from `str`. Fractional powers use `Decimal ** Decimal`.
- Quantize only on storage, as OQ-3 says: a calculated PU to 10 dp, a calculated rate to 12 dp, `ROUND_HALF_UP`; reject typed values with more decimals.

## 4. Verify and commit

Run the module's whole unit suite, plus lint and type checks. Commit the test and the code together, after the user approves (skill `commit`). **Never change an expected value to make a test pass**: a mismatch is a bug, or a `spec-gap`.
