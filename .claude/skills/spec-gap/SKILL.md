---
name: spec-gap
description: Stop and escalate when the Maravi DI1 docs are ambiguous, contradictory or silent on something needed, when a task touches an open question (OQ-…), or when code would have to deviate from the docs. Use instead of guessing.
---

# Escalate a specification gap

**Do not guess, and do not change a doc to fit your code.**

## 1. Make sure it is a real gap

- Search the docs: `grep -rn "<term>" docs/`.
- Check `docs/open-questions.md`. If it is already an OQ, cite it and treat that part as blocked.
- Check business spec §14: the decisions already closed.
- If the answer exists, use it, and cite the line in your PR.

## 2. Write it down

Put the gap in your report and in the PR description as `GAP-<lane>-<n>`. Only the integrator edits `docs/open-questions.md` and assigns the OQ number. The entry gives:

- **the question**, in one sentence;
- **where it bites:** the file, function or endpoint, and a concrete input whose result is undefined;
- **what each doc says:** quotes with file and section;
- **two or three options**, each with its consequence for the code, the tests and the other lanes;
- **your recommendation**, and why.

## 3. Keep moving without guessing

- Mark the blocked part with `# SPEC-GAP GAP-<lane>-<n>: <one line>`, and a skipped test: `pytest.mark.skip(reason="GAP-…")` or `it.todo('GAP-… …')`.
- Continue with the parts that do not depend on the answer.
- End your report with "Blocked on GAP-<lane>-<n>" and its summary.

The integrator answers from the docs, or asks the user. Answers are recorded with `record-decision`.
