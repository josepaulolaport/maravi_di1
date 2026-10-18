---
name: verification-before-completion
description: Before saying anything is done, fixed, passing or working in the Maravi DI1 project, run the command that proves it and read its output. Use before every status report, PR description, "ready" message or claim of success.
---

# Verify before claiming

Adapted for this project from the "verification-before-completion" skill of obra/superpowers (MIT).

**Rule: no claim without fresh evidence from this session.** Applies to "tests pass", "fixed", "works", "ready for review", "no regressions" and "coverage OK".

1. **Name the proof.** Which command shows the claim is true? For example:
   - `uv run pytest -q` or a specific node id;
   - `npm test`;
   - a request against the running API;
   - `git rebase origin/main --exec "<fast suite>"`.
2. **Run it now.** An earlier run, or a run before your last edit, does not count.
3. **Read the output.** Check the exit code and the summary line: failures, errors, skips, coverage. A warning or a skipped test is part of the result.
4. **Report exactly what you saw.** Copy the real summary line, e.g. `214 passed, 2 skipped in 8.1s`. Something you could not run is reported as **not verified**, with the reason (for example: no Docker here).
5. **Words to avoid without proof:** "should work", "probably", "looks fine", "I believe it passes", "done".

This is what the PR description's "Verified (command → result)" section (skill `pr-ready`) is made of.
