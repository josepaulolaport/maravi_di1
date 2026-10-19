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

## Run the application

```bash
docker compose up --build -d   # PostgreSQL 16, RabbitMQ, migrations, API, outbox relay, worker, dispatcher
make seed                      # catalogue roots: instrument type FUTURE, asset class INTEREST_RATE_FUTURE
cd frontend && VITE_API_MOCKS=false npm run dev   # UI on http://localhost:5173 against the API
```

The API answers on http://127.0.0.1:8000 (`/health`, `/api/...`), and the RabbitMQ management UI
on http://127.0.0.1:15672 (user `di1`, password `di1`). The Vite dev server proxies `/api` and
`/health` to the API; when the API runs on another port (`DI1_API_PORT`), add
`API_PROXY_TARGET=http://127.0.0.1:<port>` to the `npm run dev` command. Without
`VITE_API_MOCKS=false` the UI runs against its built-in MSW mocks, with no backend at all. `docker compose down -v` removes the
stack and its data.

## Demo: the challenge example, end to end

```bash
make e2e   # throwaway stack (project di1-e2e, API on :18000): seed, run the example, check, remove
```

`scripts/e2e_smoke.py` runs the challenge example (§5 of the challenge) through the HTTP API,
dated **today** rather than 01/01/2027 (deviation D4 below):

1. Create the product DI1 (face value 100.000) and a contract maturing today + 365 calendar days.
2. Deposit 200.000 (Lançamentos → aporte).
3. Buy 1 contract at 10% a.a. → execution PU **90.909,09** (`100000 / 1.1`).
4. Enter a reference price of 10% for today (Ativos → contrato; deviation D2).
5. Request processing, scope Tudo, from today to today (Central de Controle → Processamentos; D3).
6. Carteira for today: cash **109.090,91**, market value 90.909,09, AUM **200.000,00**.

The same steps can be done by hand in the UI. The exact example dated 01/01/2027 runs in the
automated acceptance tests with a fixed clock (`backend/tests/acceptance/`,
`backend/tests/integration/acceptance/`).

## Deviations from the challenge (spec §15)

| # | Challenge | This application | How the example still runs |
|---|---|---|---|
| D1 | §5 shows BRL as a row of the positions table (qty 109090.91, price 1) | Cash is the "Saldo em caixa" indicator, never a position row (§11.4) | Same numbers, different presentation |
| D2 | §5 values DI1F28 at the trade's own price ("available reference prices") | A reference price comes only from the exact date; an execution price never becomes a reference price (§4.2, §5) | The user also enters a 10% reference price (PU 90.909,09) for the day; the numbers then match |
| D3 | §5 and requirement 6: the query rebuilds the portfolio from the events up to the date | Rebuilding happens in a processing run the user requests; the GET only reads published results (§10, §11.4) | After a run for the date; before it the screen shows "Não processado" with a link to Processamentos |
| D4 | The examples are dated 01/01/2027, a future date when written | Dates after today are rejected (§6.1) | Automated tests run the examples exactly as written with a fixed clock; the README demo uses today |

## Known gaps and next steps

- **One worker, simpler recovery (OQ-45):** the system runs exactly one processing worker, with
  recovery at worker start. Until the worker simplification lands, the merged code (#78) still
  carries the lease and claim-token machinery that a single worker does not need; the
  `claim_token`, `lease_expires_at` and `attempt_count` columns stay in the schema, unused.
- **Catalogue roots are seeded by `make seed`, not by a migration:** the API has no route for
  instrument types and asset classes, so a fresh database needs `make seed` before the DI1 product
  can be created.
- **Reference prices are typed by hand:** there is no CSV or B3 price import yet; the B3 source
  exists in the model and the MANUAL > B3 precedence is implemented.
- **Repository housekeeping:** the `.claude/settings.json` deny list on `main` still carries
  merge-related entries from before the reviewer session was allowed to merge; an upstream MSW
  issue found by the frontend lane is still to be reported.
- Open questions and every decision taken are in [docs/open-questions.md](docs/open-questions.md).

## CI

`.github/workflows/ci.yml` runs the same targets on every pull request and on pushes to `main`.
Backend and frontend jobs run only when their files change; `ci-ok` aggregates them and is the
check to require on `main`.

AI review is [CodeRabbit](https://www.coderabbit.ai), a GitHub App installed on the repository
(free for public repositories), configured in `.coderabbit.yaml`. It is not a CI job and never
blocks a merge: it only comments, and documentation (`docs/**`, Markdown) is excluded. With fewer
than 10 repository stars CodeRabbit does not review automatically; comment
`@coderabbitai review` on the PR to start one.
