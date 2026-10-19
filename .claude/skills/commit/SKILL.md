---
name: commit
description: Make a Maravi DI1 commit the way the project requires — no per-commit approval (review at PR time), one logical change, green, test and code together, Conventional Commits message with why and Refs, generated files separate, fixups squashed before the PR. Use every time you commit.
---

# Commit

**Commit freely; review happens at PR time** (CLAUDE.md §4). Every commit is still green, one logical change, tests first.

## 1. Prepare

- Can you describe the change in one sentence without "and"? If not, split it.
- Was the test written first, and seen failing? Is everything green now? Run the tests of the area you touched.
- Take out anything unrelated: formatting, renames, debug prints, commented-out code.

## 2. Stage exactly the change and show it

```bash
git add <explicit paths>         # never `git add .` or a whole folder you did not inspect
git diff --cached --stat         # about 300 changed lines at most, lock and generated files excluded
git diff --cached
```

Check the staged diff yourself, then commit. After a commit, check that it landed (`git log -1`): if the hook failed, unstage before the next commit so nothing spills into it.

Generated files and lock files go in their own `chore` commit.

## 3. The message

```
<type>(<scope>): <imperative summary, lower case, no period, ≤ 72 chars>

<Why this change, which rule it implements, what a reviewer would
otherwise have to ask. Wrap at 72.>

Refs: spec §<n>; interfaces <module>; OQ-<n> if relevant
<attribution trailers given by your session>
```

- **Types:** feat, fix, test, refactor, perf, docs, build, ci, chore, contract.
- **Scopes** (required; the hook rejects others):
  - modules: asset, pricing, ledger, prices, portfolio, pnl, processing;
  - backend: platform, workers, composition, shared, db;
  - frontend: web, web-<feature>;
  - other: infra, ci, docs, agents.
- **`feat` and `fix` need a `Refs:` line.** A `fix` includes the regression test that reproduces the bug.

Use `git commit -F <file>` or a heredoc. **Never use `--no-verify`.**

## 4. Fixing an earlier commit of your own branch (before its PR)

```bash
git commit --fixup <sha>                                  # no per-commit approval
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash main     # before opening the PR
git rebase main --exec "<the area's fast test command>"   # every commit still green
```

Never rewrite commits that are already on `main` or in a PR under review. Never force-push.
