# Maravi DI1 Backoffice

Prices DI1 contracts (PU ↔ rate), records trades, cash movements and reference prices, and
publishes daily positions and P&L for one portfolio on request. The specification is in
[docs/](docs/README.md); agent rules are in [CLAUDE.md](CLAUDE.md).

## Setup in 30 seconds

Needs [uv](https://docs.astral.sh/uv/) 0.13+, Node 24 LTS with npm, Docker and GNU Make.

```bash
make install   # cd backend && uv sync --frozen; cd frontend && npm ci
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
docker compose up --build -d   # PostgreSQL 16, RabbitMQ, migrations, seed, API, demo data, relay, worker, web
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
make e2e   # throwaway stack (project di1-e2e-<hash>, free ports, printed): run the example, check, remove
```

Two runs at once (for example from two worktrees) need nothing extra: each checkout gets its own
project (`di1-e2e-<hash of its path>`), image tags and free ports. To fix them instead, set
`DI1_E2E_PROJECT`, `DI1_E2E_API_PORT`, `DI1_E2E_WEB_PORT` and `DI1_E2E_RABBITMQ_MANAGEMENT_PORT`.

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

## Demo data

`docker compose up` loads two weeks of demo history: after the API is healthy, the one-shot `demo`
service runs `scripts/seed_demo.py`, which writes through the HTTP API (so every validation and
pricing rule applies). The dates are relative to the **first** `up`: data written on day X is dated
X − 14 to X (São Paulo). Every later `up` finds a non-empty ledger and adds nothing ("already
loaded"); `docker compose down -v` and `up` load a fresh copy dated from that day. `DI1_DEMO=0`
turns it off (`make e2e` does, to keep its ledger empty).

- Three contracts: the January DI1 of each of the next three years (DI1F27, DI1F28 and DI1F29 when
  loaded in 2026, maturing 04/01/2027, 03/01/2028 and 02/01/2029).
- An opening deposit of 1.000.000, a second deposit, a withdrawal and, as in the challenge example,
  a deposit of 200.000 with a buy of 1 DI1F28 at 10% (DI1F28 does not mature in 365 days, so the
  challenge's figures are those of `make e2e`, not these).
- Trades typed as a rate and as a PU, a partial sale, a sale that crosses zero into a short, and a
  buy and a sale of the longest contract on one day, applied in time order.
- MANUAL reference prices typed as a rate for every calendar day, weekends included, with **one
  deliberate gap**: the longest contract (DI1F29) on X − 5.

Nothing is processed. Open Central de Controle → Processamentos and process Tudo from X − 14 to
X: the run ends "Concluído com pendências", with a missing-price Pendência for the gap, and from
that date the cumulative P&L is unavailable. `docker compose logs demo` lists everything it wrote.

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

## Known limitations / technical debt

A staff review of the whole repository before delivery found these. The user chose to record them
rather than refactor before delivery (OQ-47); none changes a business result.

- **Two repositories for `processing.requests` (M1):** `SqlRequestRepository` (HTTP side) and the
  worker's run store both read and write the table.
- **Import cycle and no processing domain (M8):** portfolio and processing import each other's
  `public.py`, and processing's run state machine lives in `application/`, with no `domain/` package.
- **Wiring differs per module (M10):** routers and dependency providers are not built the same way
  in every module.
- **Three decimal-string types (M11):** the HTTP schemas of asset, ledger and prices each define
  their own decimal-string type instead of sharing one.
- **Two `FuturesTerms` classes (M12):** one in asset's domain, one in pricing's.
- **Timestamp types (M13):** timestamps are not typed the same way across modules.
- **A migrated database per test (M14):** integration tests migrate a fresh database each, which
  makes the backend suite slow.
- **Sleep-based race tests (M15):** some concurrency tests rely on `sleep` for ordering instead of
  explicit synchronisation, so they are slower and could flake on a loaded machine.
- **The MSW mock reimplements backend rules (H6):** the dev mocks in `frontend/src/api/mocks/`
  recompute pricing, the cash and positions chains, the predecessor rule and date statuses; they
  can drift from the backend, which is the authority (the production build has no mocks).
- **Unused schema columns and statuses (H5):** `DISPATCHED`, `CANCELLING`, `claim_token`,
  `lease_expires_at`, `attempt_count`, `dispatched_at` and `calculation_state` stay in the schema,
  unused, with no migration to drop them (OQ-45, OQ-46, OQ-47; [docs/schema.md](docs/schema.md)).

## CI

`.github/workflows/ci.yml` runs the same targets on every pull request and on pushes to `main`.
Backend and frontend jobs run only when their files change; `ci-ok` aggregates them and is the
check to require on `main`.

AI review is [CodeRabbit](https://www.coderabbit.ai), a GitHub App installed on the repository
(free for public repositories), configured in `.coderabbit.yaml`. It is not a CI job and never
blocks a merge: it only comments, and documentation (`docs/**`, Markdown) is excluded. With fewer
than 10 repository stars CodeRabbit does not review automatically; comment
`@coderabbitai review` on the PR to start one.
