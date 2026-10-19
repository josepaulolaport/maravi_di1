---
name: systematic-debugging
description: Find the root cause before fixing any bug, failing test, wrong number or unexpected behaviour in the Maravi DI1 project — reproduce, compare with working code, test one hypothesis at a time, then fix test-first. Use whenever something fails and the cause is not already proven.
---

# Systematic debugging

Adapted for this project from the "systematic-debugging" skill of obra/superpowers (MIT). Project rules win where they differ.

**Rule: no fix without a proven root cause.** "Try changing X and see" is not a fix.

## 1. Investigate the root cause

- **Read the whole error:** the full traceback, the assertion diff, the HTTP error body. Do not skim.
- **Reproduce it reliably**, with the smallest command: one pytest node id or one vitest test. If you cannot reproduce it, you do not understand it yet.
- **Check what changed:** `git log --oneline origin/main..HEAD`, `git diff origin/main...HEAD -- <area>`. Did a contract change, or a rebase on a merged lane?
- **Across layers** (router → service → domain → repository → database; or dispatcher → outbox → relay → broker → worker), log or inspect the value at each boundary. Find the first layer where it is wrong.
- **For a wrong number, trace it back to its inputs.** Recompute it independently with Python `decimal` from the formula in the business spec (§4, §7, §8).

## 2. Compare with what works

- Find working code or a passing test in this repository that does the same kind of thing, and list every difference.
- Re-read the governing doc: the business spec section, `interfaces.md`, `schema.md`. A "bug" may be the code following an outdated reading. If the docs themselves are unclear, run `spec-gap`.

## 3. One hypothesis at a time

- State it in one sentence: "The average is wrong because crossing zero keeps the old average."
- Test it with the smallest possible change or probe. If it fails, discard it and form a new one. Never stack guesses.

## 4. Fix test-first

1. Write a test that **reproduces the bug** and fails for the right reason. This is the regression test.
2. Make one fix at the root cause, not at the symptom.
3. Run the area's whole suite, then commit the test and the fix together: `fix(<scope>): …` with `Refs:` (skill `commit`).

## Stop signs

- **Three fixes have failed.** Stop patching. The model of the problem is wrong, or the design is. Report it to the integrator with what you learned.
- **"It works if I change the expected value."** That is never the fix. The expected values come from the docs.
- **"It's flaky."** Find the shared state, time or ordering dependency. Do not retry or sleep it away.
