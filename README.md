# Maravi DI1 Backoffice

Prices DI1 contracts (PU ↔ rate), records trades, cash movements and reference prices, and
publishes daily positions and P&L for one portfolio on request. The specification is in
[docs/](docs/README.md); agent rules are in [CLAUDE.md](CLAUDE.md).

## Setup in 30 seconds

Needs [uv](https://docs.astral.sh/uv/) 0.13+, Docker and GNU Make (Node 24 once `frontend/` exists).

```bash
make install   # cd backend && uv sync --frozen; npm ci once frontend/package.json exists
make lint      # uv lock --check, ruff check, ruff format --check, mypy (strict);
               # frontend: eslint, tsc --noEmit, prettier --check
make test      # one Alembic head, alembic upgrade head, pytest with coverage on PostgreSQL 16
git config core.hooksPath scripts/git-hooks   # pre-commit and commit-msg hooks
```

`make test` starts a throwaway `postgres:16` container on a free port and removes it afterwards.
With `TEST_DATABASE_URL` set (an admin URL, `postgresql+psycopg://user:pw@host:port/postgres`) it
uses that server instead. Database tests are required (`REQUIRE_DATABASE_TESTS=1`): they never skip.

Split targets: `make {install,lint,test}-{backend,frontend}`, and `make lint-commits` checks the
messages of `origin/main..HEAD`.

## CI

`.github/workflows/ci.yml` runs the same targets on every pull request and on pushes to `main`.
Backend and frontend jobs run only when their files change; `ci-ok` aggregates them and is the
check to require on `main`.

The AI review job (`scripts/ai_review.py`) runs after `ci-ok` passes. It sends the PR diff to
Google's Gemini API (`gemini-3.8-flash`) in one request, or a few for a large diff, and posts one
review with an inline comment per finding. The reviewer's instructions are in
`.github/ai-review/prompt.md`; the answer, also kept as `review.json` in the run's `ai-review`
artifact, must match `.github/ai-review/review.schema.json`. It needs one repository secret,
`GEMINI_API_KEY`, holding a Google AI Studio API key; until it is set the job fails without
blocking the merge. On the free tier Google may use the prompts to improve its products, and
fork PRs get no review (secrets are unavailable to them). PRs that change only documentation
(`docs/**` or Markdown files) skip it; Markdown is also left out of a mixed PR's review.
