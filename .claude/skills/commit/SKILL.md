---
name: commit
description: Make a Maravi DI1 commit the way the project requires — the user approves the diff first, one logical change, green, test and code together, Conventional Commits message with why and Refs, generated files separate, fixups squashed before the PR. Use every time you commit.
---

# Commit

**Nothing is committed without the user's approval.** Prepare the change, show it, and wait.

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

Show the user the staged diff and the proposed message. **Commit only after the user says yes.**

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
git commit --fixup <sha>                                  # also after the user's approval
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash main     # before opening the PR
git rebase main --exec "<the area's fast test command>"   # every commit still green
```

Never rewrite commits that are already on `main` or in a PR under review. Never force-push.
