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
docker compose up --build -d   # PostgreSQL 16, RabbitMQ, migrations, seed, API, outbox relay, worker, web
```

On every `up`, after the migrations, the one-shot `seed` service applies
`scripts/seed_catalogue.sql`: the instrument type FUTURE, the asset class INTEREST_RATE_FUTURE and
the DI1 product (face value 100.000), which the UI cannot create (Ativos only browses products,
spec §11.2). It is idempotent and keeps rows that already exist; `make seed` applies it again by
hand. A fresh stack can therefore create a DI1 contract at once (Ativos → DI1 → Novo contrato) and
trade it.

Then open http://localhost:8080: the `web` service serves the built UI (nginx) and forwards `/api/`
and `/health` to the API, so the UI runs on the real backend (no MSW mocks in the build). The API
also answers directly on http://127.0.0.1:8000 (`/health`, `/api/...`), and the RabbitMQ
management UI on http://127.0.0.1:15672 (user `di1`, password `di1`). Ports are set with
`DI1_WEB_PORT`, `DI1_API_PORT` and `DI1_RABBITMQ_MANAGEMENT_PORT`.
`docker compose down -v` removes the stack and its data.

For frontend development, run the Vite dev server against the same stack:

```bash
cd frontend && VITE_API_MOCKS=false npm run dev   # UI on http://localhost:5173 against the API
```

The dev server proxies `/api` and `/health` to the API; when the API runs on another port
(`DI1_API_PORT`), add `API_PROXY_TARGET=http://127.0.0.1:<port>` to the `npm run dev` command.
Without `VITE_API_MOCKS=false` the dev UI runs against its built-in MSW mocks, with no backend at
all.

### Processing: why RabbitMQ

Processing runs only when the user requests it, in one worker process (OQ-45, OQ-46).
`POST /processing/requests` saves the request as `QUEUED` in PostgreSQL and, in the same
transaction, an outbox message that only means "there is work". The outbox relay publishes it to
RabbitMQ with publisher confirms. The worker wakes up on that message, takes the oldest `QUEUED`
request from PostgreSQL under a row lock, runs it, and repeats until none is left.

- **PostgreSQL is the source of truth** for the requests, their order and their status;
  RabbitMQ never records what is pending.
- **RabbitMQ is the push wake-up**: the API answers at once, and processing runs off the request
  path, in a separate process, with no polling. This is where messaging adds value (challenge §8).
- **A lost or duplicated message is harmless**: the next message, or the next worker start, drains
  the `QUEUED` requests; a message that finds nothing to do does nothing.
- Rejected alternative: PostgreSQL LISTEN/NOTIFY or polling. It removes one service, but it drops
  the messaging part of the challenge and would rework tested code.

## Demo: the challenge example, end to end

```bash
make e2e   # throwaway stack (project di1-e2e, API on :18000): run the example, check, remove
```

`scripts/e2e_smoke.py` runs the challenge example (§5 of the challenge) through the HTTP API,
dated **today** rather than 01/01/2027 (deviation D4 below):

1. Use the seeded product DI1 (face value 100.000) and create a contract maturing today + 365
   calendar days.
2. Deposit 200.000 (Lançamentos → aporte).
3. Buy 1 contract at 10% a.a. → execution PU **90.909,09** (`100000 / 1.1`).
4. Enter a reference price of 10% for today (Ativos → contrato; deviation D2).
5. Request processing, scope Tudo, from today to today (Central de Controle → Processamentos; D3).
6. Carteira for today: cash **109.090,91**, market value 90.909,09, AUM **200.000,00**.

The same steps can be done by hand in the UI. The exact example dated 01/01/2027 runs in the
automated acceptance tests with a fixed clock (`backend/tests/acceptance/`,
`backend/tests/integration/acceptance/`).

## Interpretations, additions and deviations (spec §15)

### Interpretations (ambiguous text)

| # | Challenge | Reading adopted | Why |
|---|---|---|---|
| I1 | §3: the contract has an identifier, **reference date**, maturity and rate or PU | The contract has an identifier and a maturity; the reference date and rate/PU belong to the calculator, the trade or the reference price | The same data, split between the static contract and the dated events |
| I2 | §4.2: cash balance = inflows − outflows | Cash also includes the trades' financial effect (§7.3) | The §5 example requires it: cash 109.090,91 after the purchase |
| I3 | §5: "Financeiro total: 200.000" | AUM = cash + market value (§8.2) | 200.000 = 109.090,91 + 90.909,09 |
| I4 | §5: "Resultado financeiro simplificado da posição" | Market value (`financial_total`) and positions and trades P&L (§8) | The challenge does not define the metric |

### Additions (they reject nothing the challenge describes, except D4)

Mandatory trade time (§6.1); maturity rules (§7.4); MANUAL and B3 price sources (§5); Pendências and
processing on request (§10).

### Deliberate deviations

| D1 | §5 shows BRL as a row of the positions table (qty 109090.91, price 1) | Cash is the "Saldo em caixa" indicator, never a position row (§11.4) | Same numbers, different presentation |
| D2 | §5 values DI1F28 at the trade's own price ("available reference prices") | A reference price comes only from the exact date; an execution price never becomes a reference price (§4.2, §5) | The user also enters a 10% reference price (PU 90.909,09) for the day; the numbers then match |
| D3 | §5 and requirement 6: the query rebuilds the portfolio from the events up to the date | Rebuilding happens in a processing run the user requests; the GET only reads published results (§10, §11.4) | After a run for the date; before it the screen shows "Não processado" with a link to Processamentos |
| D4 | The examples are dated 01/01/2027, a future date when written | Dates after today are rejected (§6.1) | Automated tests run the examples exactly as written with a fixed clock; the README demo uses today |

## Known gaps and next steps

- **One worker, recovery at its start (OQ-45):** the system runs exactly one processing worker;
  the schema keeps `claim_token`, `lease_expires_at` and `attempt_count` unused (OQ-45).
- **The catalogue is seeded by a Compose step, not by a migration:** the API has no route for
  instrument types and asset classes and the UI none for products, so the `seed` service applies
  `scripts/seed_catalogue.sql` (FUTURE, INTEREST_RATE_FUTURE, DI1) on every `docker compose up`.
- **Reference prices are typed by hand:** there is no CSV or B3 price import yet; the B3 source
  exists in the model and the MANUAL > B3 precedence is implemented.
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
