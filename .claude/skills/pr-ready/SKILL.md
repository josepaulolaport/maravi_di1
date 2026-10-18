---
name: pr-ready
description: Run the Maravi DI1 definition of done before opening a GitHub pull request — ownership check, all checks for the touched areas, history check, independent reviewer, honest PR description — then push the branch and open the PR for human review. Never merges. Use before every PR.
---

# Get a change ready and open the PR

Run each step and record its real result. Never write "passes" for something you did not run.

## 1. Scope and ownership

```bash
git fetch origin && git rebase origin/main
git diff --name-only origin/main...HEAD
```

- **Every changed path is in your lane's ownership** (plan §2). Shared files are owned by the integrator:
  - `composition/`, `main.py`, `shared/`;
  - `migrations/`;
  - `pyproject.toml`, `uv.lock`;
  - `compose.yaml`, CI.
- **No commit is pending the user's approval.** Every commit on the branch was approved.

## 2. Checks for the touched areas

- **Backend** (from `backend/`):
  - the unit tests;
  - the integration tests against your worktree's PostgreSQL;
  - `tests/architecture/`;
  - `ruff check`, `ruff format --check`;
  - the type checks;
  - for schema work, the migration on a fresh database.
- **Frontend** (from `frontend/`): lint, the type check and the tests.
- **History:**

  ```bash
  GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash origin/main
  git log --format='%h %s' origin/main..HEAD
  git rebase origin/main --exec "<fast test command>"
  ```

  - Each commit is one logical change, and every commit is green.
  - No test was deleted, weakened or skipped. Check with `git diff origin/main...HEAD -- '*test*'`.

## 3. Independent review

Run the `reviewer` subagent in a fresh context, on the diff, with your lane, your wave and the spec sections. Fix every Blocker and Major finding. Answer the others in the PR description.

## 4. Push and open the PR (no merge, ever)

```bash
git push -u origin HEAD                # never --force
gh pr create --base main --title "<lane> <wave>: <summary>" --body-file <file>
```

The PR body:

```
<lane> <wave>: <summary>

Spec: §…  Interfaces: <module>  Open questions touched: none | OQ-…
Contract changes: none | <list, needs integrator>
Docs to update (integrator applies): none | <file § — old → new>

Verified (command → result):
- <command> → <copy the real summary line>
Reviewer: <No findings | findings and how they were addressed>

Open gaps: none | GAP-<lane>-<n>: <question>
Not verified / known limits:
- …
```

A human reviews and merges it on GitHub. Never run `gh pr merge` or `git merge`. Give the user the PR URL.
