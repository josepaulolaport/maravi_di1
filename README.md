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

AI review is [CodeRabbit](https://www.coderabbit.ai), a GitHub App installed on the repository
(free for public repositories), configured in `.coderabbit.yaml`. It is not a CI job and never
blocks a merge: it only comments, and documentation (`docs/**`, Markdown) is excluded. With fewer
than 10 repository stars CodeRabbit does not review automatically; comment
`@coderabbitai review` on the PR to start one.
