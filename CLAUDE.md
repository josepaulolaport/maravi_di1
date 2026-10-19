# Maravi DI1 Backoffice: instructions for every agent

You are one agent in a small team building, in parallel lanes, a web application that:
- prices DI1 contracts (PU ↔ rate);
- records trades, cash movements and reference prices;
- publishes daily positions and P&L for **one** portfolio, but only when the user asks for processing.

It is a technical challenge, and every decision may be questioned in an interview. Your work must be **correct, explainable and verified**.

## 1. The docs are the specification

Everything is in [docs/](docs/README.md). **Build what they say; do not redesign.**

Order of authority:

1. The challenge text, `docs/desafio_tecnico_di1_1.pdf`, except the deliberate deviations D1–D4 in spec §15.
2. `docs/maravi_business_specification.md`, for behaviour.
3. `docs/schema.md` / `schema.sql`, `docs/interfaces.md` and `docs/maravi_implementation_plan.md`, for execution.
4. Code comments, chat history and your assumptions: never authoritative.

If the docs are ambiguous, contradictory or silent on something you need, **stop that part** and use the `spec-gap` skill. Check `docs/open-questions.md` first. Code that depends on an open question (OQ-…) is not written until the user answers it.

## 2. Rules that are easy to get wrong

- **Exactly one portfolio.** No `portfolio_id` and no portfolio entity anywhere.
- **Money, PU and rates are `Decimal`, never `float`.**
  - SQL uses `NUMERIC`.
  - JSON carries decimal strings.
  - The frontend only formats; it never calculates.
- **Pricing uses DC/365 with calendar days:**
  - `PU = 100000 / (1 + taxa)^(dias_corridos/365)`
  - `taxa = (100000/PU)^(365/dias_corridos) − 1`
  - The rate is a fraction (0.10 = 10% a.a.). Rate **or** PU is typed, and the other is computed.
  - Precision (OQ-3): `Decimal` at 34 digits, `ROUND_HALF_UP`. A calculated PU is stored with 10 dp, a calculated rate with 12 dp. A typed value with more decimals is **rejected**, never rounded. Money is stored exact and rounded to 2 dp only for display.
  - The multiplier is stored but **not applied** (OQ-2).
- **Three different prices:**
  - a *calculated* price, which is never stored as such;
  - an *execution* price (Ledger, immutable trade);
  - a *reference* price (Prices).
  - A trade price never becomes a reference price.
- **Reference prices:**
  - **Exact date only. No carry-forward**, weekends included.
  - When both sources exist, MANUAL wins over B3.
  - There is one row per (asset, date, source) and no revisions (OQ-25): a correction updates it in place, a removal deletes it.
  - Prices live only in the price table (OQ-30): the Carteira shows each date's reference PU, rate and source from the current preferred price, and `position_metrics` stores no PU or source. D's position P&L uses the D−1 PU from the price table. A price changed after its date was processed marks nothing (OQ-31): the processed dates keep their status until the user reprocesses them.
- **Accounting:**
  - Starting state: zero cash, zero positions, zero P&L.
  - **Every calendar day** is processed.
  - Trades are applied in chronological order (date, time, `seq`), never netted first.
  - Signed quantities and weighted average PU. The average rate is weighted on its own.
  - A partial reduction keeps the average.
  - A trade that crosses zero closes the old position and opens the rest at the trade's PU. The ledger row is never split.
  - Cash: `cash[D] = cash[D−1] − Σ(signed_qty × execution_PU) + deposits − withdrawals`. Cash and positions are two independent chains, processed and published separately (OQ-21); they meet only in AUM.
  - P&L is never posted to cash.
- **P&L: compute per asset first, then aggregate.**
  - `position_pnl = Q[D−1] × (PU_D − PU_{D−1})`
  - `trades_pnl = Σ q_i × (PU_D − PU_exec_i)`
  - `daily = position_pnl + trades_pnl`
  - `cumulative = previous + daily`
  - Deposits and withdrawals are never P&L.
  - No realized/unrealized P&L in the default view.
- **AUM = cash + Σ signed market value** (`financial_total = Q × reference_PU`). There are no exposure fields and no `total_equity`. AUM is `null` when either chain is missing, or when the other chain of the date is not `PROCESSED`/`PROCESSED_WITH_ISSUES`, whichever run wrote it (OQ-38, OQ-40; on ALL it is computed after both chains are written); it has no status of its own, so the screens show the cash and positions statuses (OQ-28); whichever scope publishes recomputes it (OQ-21).
- **Missing price:**
  - Quantity, average cost and cash are still computed.
  - The dependent figures are `null`, never zero.
    - Sole exception (OQ-41): the Carteira chart's running sum `range_cumulative_pnl`, where a date adds 0 unless its positions status is `PROCESSED`/`PROCESSED_WITH_ISSUES` and its `daily_pnl` is not null.
  - The portfolio total is not complete if any expected asset is missing. An asset is expected on D when Q[D−1] ≠ 0 or it trades on D (OQ-10).
  - When Q[D−1] = 0, `position_pnl` = 0 exactly (OQ-4).
  - The cumulative P&L stays unavailable from the first gap onward.
    - Sole exception (OQ-41): the Carteira chart's running sum `range_cumulative_pnl`, where a date adds 0 unless its positions status is `PROCESSED`/`PROCESSED_WITH_ISSUES` and its `daily_pnl` is not null.
  - A missing price is not a technical failure: the job ends `COMPLETED_WITH_ISSUES`.
- **No automatic processing.**
  - A write saves the fact. **Nothing else** (OQ-31): nothing is marked stale, Ledger and Prices do not call Processing, and there is no `FinancialResultInvalidator`. Processed results stay as they are until the user processes again; after changing history, the user reprocesses.
  - Processing runs only when the user requests a date range.
- **Jobs:**
  - PostgreSQL holds the queue and the job statuses; RabbitMQ only carries dispatch commands.
  - Many jobs may be queued, and only one runs at a time.
  - Cancellation is cooperative.
  - No staging (OQ-23): each date is published in its own transaction, which locks the `date_status` rows of D−1 and D and checks the claim token. A write during a run only saves its fact; the run never stops for it (OQ-31).
  - `processing.date_status` is the only source of each date's processing status (OQ-23, OQ-31), per chain: no row or NULL = Não processado, `PROCESSED` Processado, `PROCESSED_WITH_ISSUES` Processado com pendências, `RUNNING` Processando, `FAILED` Erro. There is no `STALE`. `cash_processed_at` and `portfolio_processed_at` record when a run last committed each chain for the date (NULL when never processed); every read exposes them, and the UI shows "Processado em dd/mm/aaaa hh:mm". There are no dirty markers and no revision counters.
  - Eight run statuses; there is no `SUPERSEDED`. A failure at D sets D `FAILED` and ends the run `FAILED`, except on an ALL run where one chain fails: the run then ends `COMPLETED_WITH_ISSUES`, and `FAILED` only if both fail; `COMPLETED_WITH_ISSUES` and `CANCELLED` may carry `error_code`/`error_message` (OQ-36). The run stores its first failure as `failed_date` and `failed_chain`; a `COMPLETED_WITH_ISSUES` run where a chain failed offers "Solicitar novo processamento" with that chain's scope from `failed_date` to the original end (OQ-40). A cancel commits the current date and ends `CANCELLED`. Later dates are never touched. Recovery resumes after `requests.progress_date`.
- **Ledger entries are never edited.** Trades and cash movements are one ledger entry (`ledger.entries`, OQ-24). They are deleted only by an explicit user action (OQ-32): a real `DELETE`, without a reason, all or nothing, with no audit trail; an unknown or already-deleted id answers 404 and nothing is deleted.
- **Dates and validation** (OQ-7, OQ-13, OQ-14):
  - Any calendar date, weekends and holidays included.
  - Nothing dated after today (America/Sao_Paulo, through an injected clock); maturities are exempt. A processing range ending after today is rejected too (OQ-29).
  - `entry_time` is required for trades and cash movements alike. Same-date order across both: `(entry_date, entry_time, seq)` (OQ-24).
  - Value bounds are only the schema's CHECKs.
- **Maturity** (OQ-1):
  - No automatic settlement. The user closes with a normal trade, at any PU, up to the maturity date inclusive. On the maturity date the PU is typed and the rate is stored as 0.
  - The maturity-day reference price is entered by the user.
  - After maturity the reference PU is 0 by definition, and trades and prices dated after it are rejected. An open position then raises the Pendência "contrato vencido com posição aberta".
- **Processing ranges** (OQ-11, OQ-21, OQ-23, OQ-30, OQ-31, OQ-36, OQ-40):
  - A job has a scope: CASH, POSITIONS or ALL. Each scope reads and sets only its own chain's status; ALL writes both chains of a date, and its AUM, in one transaction.
  - A job processes exactly [A, B], with no expansion.
  - Predecessor rule, per day, for both chains (OQ-31): a run may start on any date. For each date D of a chain, D−1 must be `PROCESSED` or `PROCESSED_WITH_ISSUES`, or the chain's zero state: no date before D has any status for the chain and no entry of the chain's type on or before D−1 (positions: no trade; cash: no entry of either type; OQ-26, OQ-32, OQ-40 item 5). Otherwise D gets `FAILED` (Erro) with `CASH_PREDECESSOR_MISSING` or `POSITIONS_PREDECESSOR_MISSING` and "Dia anterior não processado", the run ends `FAILED`, and later dates are not touched. A `FAILED` D−1 counts as not processed. D−1 `FAILED` or `RUNNING`, or a gap after an earlier status, fails D first; Ledger is asked for the zero state only when the chain has no status before D (OQ-37, OQ-40 item 5). Since dates run in order, this can only happen on a run's first date. On an ALL run, the failing chain stops and the other is still written on D, in the same transaction, and continues; the run ends `COMPLETED_WITH_ISSUES` with the error, or `FAILED` if both fail. On ALL, D runs in one transaction with a SAVEPOINT per chain: a technical error rolls back only the failing chain; an error in a chain's writer call (which recomputes AUM) belongs to that chain; a non-chain failure (outside every chain's savepoint; integrator choice) rolls back all of D, sets D `FAILED` for every chain still alive in the run and ends the run `FAILED`; a lost lease is not a failure at D (OQ-40). Recovery keeps a chain with a `FAILED` date in the run stopped (read from `date_status`); a cancel after a chain failed ends `CANCELLED` and keeps the first failure's error (OQ-36), `failed_date` and `failed_chain`, and offers the failed-chain retry too (OQ-40 item 6).
  - Pendências have two types (OQ-31): `MISSING_REFERENCE_PRICE` and `EXPIRED_OPEN_POSITION`. There is no `STALE_PREDECESSOR`. They are deduplicated on read (OQ-37): one row per (asset, required price date) for a missing price, one per asset for an expired position, each with its earliest affected date.
  - There is no cancel-and-replace (OQ-30): cancel and queue are separate actions.
  - A day with no expected asset is still processed: P&L 0, AUM = cash when the cash chain is processed on that date, otherwise null (OQ-38), cumulative P&L carried forward (OQ-22).
  - There are no dirty markers: each published date sets its own status and processing time in `date_status` (OQ-23, OQ-31).
- **All user-facing text is Brazilian Portuguese**, with Brazilian formats. Code and identifiers are English.

## 3. Architecture

**Stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 **async**, PostgreSQL 16, Alembic, `uv`, RabbitMQ via **aio-pika**.
- Frontend: Vite, React with TypeScript (`strict`), React Router, Mantine (`core`, `hooks`, `form`, `dates` with dayjs, `notifications`, `charts`), Tabler icons, TanStack Query, MSW, Vitest with Testing Library and jsdom, ESLint (typescript-eslint, react-hooks) and Prettier; Node 24 LTS with npm. The designs live in Figma, read through the Figma MCP server. Details are in `frontend/CLAUDE.md`.
- Docker Compose runs the API, PostgreSQL, RabbitMQ, the worker, the dispatcher and the outbox relay.

**Modular monolith:** the modules are `asset`, `pricing`, `ledger`, `prices`, `portfolio`, `pnl` and `processing`; `platform` holds the shared technical infrastructure. The layout is in `docs/maravi_implementation_plan.md` §1:
- `backend/src/di1/modules/<m>/{public.py, domain/, application/services/, application/interfaces/, infrastructure/, presentation/http/, presentation/messaging/}`
- `infrastructure/` holds persistence and any other outbound adapter. A module's RabbitMQ consumers and handlers live in `presentation/messaging/`; shared RabbitMQ infrastructure lives in `platform/messaging/`; business processing logic stays in `application/`.
- `composition/`, `workers/`, `platform/`

**Rules:**
- Cross-module access goes **only** through `public.py` DTOs and services. Never import another module's ORM or repositories.
- Domain code, including the calculators (`pricing`, `pnl`, portfolio accounting), is deterministic, synchronous and free of I/O and side effects: no filesystem, network, database, messaging, environment or system-clock access, and no FastAPI. Pure standard-library utilities (`datetime` arithmetic, `Decimal`, `Enum`, `dataclasses`) are allowed.
- Domain code does not log: logging belongs in the application, infrastructure or presentation layers, and the domain reports failures through exceptions and explicit results. It never generates randomness internally: a calculation that needs it (e.g. Monte Carlo) takes an explicit seed or an injected random-number generator.
- SQL lives in `infrastructure/persistence/queries`.
- FastAPI `Depends` is used only in HTTP adapters and dependency providers. Workers use plain factories.
- One Unit of Work per operation; a write saves only the fact (no invalidation, OQ-31).
- Cohesive application services, not a class per command.

## 4. How we work

- **One agent, one lane, one git worktree, one branch.** Lanes and owned paths are in plan §2:
  - A–G are the modules;
  - H is platform;
  - I is frontend;
  - X is the integrator.

  Edit only your lane's paths. To change anything else, raise a contract-change request to the integrator (X).
- **Commits need the user's approval.** Prepare the change, show the diff (`git diff`, `git diff --cached`), and commit only after the user says so.
- **Nobody merges.** Not you, not the integrator.
  - When a branch is ready, and its commits are approved, push the branch and open a GitHub pull request with `gh pr create` (skill `pr-ready`).
  - A human reviews and merges it on GitHub.
  - Never `git merge` into `main`, never `gh pr merge`, never force-push, never `--no-verify`.
- **Commits** (skill `commit`):
  - Conventional Commits, `<type>(<scope>): <summary>`, with a body that explains why and a `Refs:` line citing the spec section.
  - One logical change per commit. Every commit is green: it builds, passes lint and types, and every test passes.
  - Test and code go in the same commit.
- **Tests first** for every rule, using the cases in spec §13 (skill `tdd`). Expected values come from the docs, never from running the code. Never delete, weaken or skip a test to make a change pass.
- **A new worktree needs its dependencies once** before its first commit: `cd backend && uv sync --frozen`, and `cd frontend && npm ci` once the frontend exists. The pre-commit hook runs the backend checks (ruff, mypy, unit and architecture tests) and, once `frontend/package.json` exists, the frontend checks (eslint, tsc, vitest), and it fails if those dependencies are missing.
- **Integration tests use PostgreSQL**, never SQLite. Each worktree has its own database or schema namespace; never share one mutable dev database.

## 5. Definition of done (skill `pr-ready`)

A change is done only when all of these hold, and you have run them:

- the unit and integration tests for the touched area;
- lint and formatting;
- type checks;
- the import-boundary tests;
- for schema work, the migration applied to a fresh database.

The PR description lists:
- the spec sections covered;
- the commands run, each with its real result line;
- what was **not** verified;
- open questions;
- any deviation from the spec.

Never claim something passes, runs or is fixed unless you ran it and saw it. Say "not run" or "not verified" plainly.

## 6. Agents and skills

- **Roles** (`.claude/agents/`):
  - `integrator`: lane X; composition, migrations, contracts, compose, CI.
  - `module-engineer`: lanes A–G; started with its lane.
  - `platform-engineer`: lane H.
  - `frontend-engineer`: lane I.
  - `reviewer`: runs in a fresh context on every PR before it is opened.
- **Skills** (`.claude/skills/`):
  - `commit`, `tdd`, `spec-gap`, `record-decision`;
  - `add-endpoint`, `frontend-screen`, `db-migration`;
  - `pr-ready`, `systematic-debugging`, `verification-before-completion`.

## 7. Communication

Be direct and precise: say what you assumed, what you verified, and what is still open. When compacting context, keep:
- your lane;
- your task;
- the spec sections;
- the files you changed;
- the commands still to run.
