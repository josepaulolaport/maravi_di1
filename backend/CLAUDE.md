# Backend rules (loaded when you work in backend/)

These rules add to the root CLAUDE.md. The authorities are:
- `docs/interfaces.md`: contracts, transactions, endpoints;
- `docs/schema.md` / `docs/schema.sql`: the database;
- `docs/maravi_implementation_plan.md` §1: the layout.

## Layout (plan §1)

```text
backend/
  pyproject.toml  uv.lock  alembic.ini
  migrations/{env.py, versions/, sql/}  # integrator (X) only; sql/ holds each revision's reviewed SQL; revisions 0001–0007 (head 0007) = docs/schema.sql
  src/di1/
    main.py                              # integrator
    composition/{routers,dependencies,consumers}.py   # integrator
    platform/{config.py, database/, messaging/, observability/}   # lane H
    shared/                              # only DTOs that are genuinely shared; integrator
    modules/<module>/                    # lanes A–G
      public.py
      dependencies.py                    # if needed
      domain/
      application/ports.py               # the repository Protocols the services use
      application/services/
      infrastructure/persistence/{models.py, repositories.py, queries/}
      infrastructure/<adapter>/          # other outbound adapters, when needed
      presentation/http/{router.py, schemas.py}
      presentation/messaging/            # this module's RabbitMQ consumers and handlers
    workers/{main.py, outbox_relay.py}   # lane H; no dispatcher (OQ-46)
  tests/{unit/<module>/, integration/, architecture/, fakes/}
  tests/acceptance/                  # spec §13 phase 1, pure; acceptance-tests session
  tests/integration/acceptance/      # spec §13 phase 2; acceptance-tests session
```

There is no `tests/e2e/`: the end-to-end smoke is `scripts/e2e.sh` + `scripts/e2e_smoke.py`, run by `make e2e` from the repository root.

Create only the files and packages that are used. Initially only Processing has a messaging consumer. Its handlers parse the message and call `application/`, and hold no business logic. Shared RabbitMQ infrastructure (connection, publisher, consumer base and job loop, envelope, outbox, topology) lives in `platform/messaging/`.

## Python rules

- **Typing and data:**
  - Full type hints.
  - Domain values are frozen dataclasses.
  - Pydantic v2 is used only in `presentation/` (HTTP schemas, message payloads) and `platform/` (settings).
  - Decimal fields cross HTTP as strings.
- **Domain code**, the calculators (`pricing`, `pnl`, portfolio accounting) included, is synchronous, deterministic and free of I/O and side effects:
  - no filesystem, network, database, messaging, environment or system-clock access;
  - no session, broker or FastAPI dependency;
  - "today" arrives as an argument, never from `datetime.now()` or `date.today()`;
  - pure standard-library utilities are fine: `datetime` arithmetic, `Decimal`, `Enum`, `dataclasses`, `uuid.UUID`;
  - no logging: log in `application/`, `infrastructure/` or `presentation/`; the domain reports failures through exceptions and explicit results;
  - no internal randomness: a calculation that needs it takes an explicit seed or an injected generator (`rng: random.Random`, or `random.Random(seed)`); the module-level `random` functions, `random.seed`, `SystemRandom` and an unseeded `random.Random()` are rejected.
- **Services:**
  - Services and HTTP may be `async`.
  - A service is built per request on its Unit of Work (`build_<module>_service(uow, ...)` in the module's `dependencies.py`) and keeps it; its methods never take `uow` (staff review S1; Portfolio and Processing adopt it in later PRs). A write saves only the fact, then commits once. There is no invalidation and no `FinancialResultInvalidator`: Ledger and Prices never call Processing (OQ-31).
  - A write never enqueues processing.
- **Persistence:**
  - The ORM models mirror `docs/schema.sql` exactly; do not invent columns. A schema change needs the user's decision first (`spec-gap`).
  - Repositories map rows to DTOs and hold no business rules.
  - Never expose an ORM type across modules.
- **Decimal:**
  - Construct from `str`, never from `float`.
  - The multiplier is not applied (OQ-2).
  - Fractional powers use `Decimal ** Decimal`; never `math.pow` or a float exponent.
  - One shared context: 34 digits, `ROUND_HALF_UP` (OQ-3). Quantize only on storage (a calculated PU to 10 dp, a calculated rate to 12 dp). A typed value with more decimals is rejected.
- **Messaging:**
  - RabbitMQ delivery is at least once, and a message is only a hint: a handler takes the waiting work from PostgreSQL (the oldest `QUEUED` request, OQ-50) or finds none, so a duplicate is harmless, and the worker's periodic sweep takes work whose message was lost. There is no inbox, dead-letter queue or redelivery.
  - Acknowledge once the start the message asks for is committed or skipped.
  - Publish only through `platform.outbox_messages` and the relay.
- **Errors** are RFC 9457 problem+json with `errors[{code, message, field}]`; codes from the catalogue in `docs/interfaces.md` "Errors" (OQ-15).
  - Raise a business error as `DomainError(ErrorDetail(code, "<pt-BR message>", "<field>"))` from `di1.shared.errors`, in `domain/` or `application/`. `composition/errors.py` renders it; never build an error response yourself.
  - One `DomainError` holds details of one status only (all 422, say); mixing statuses answers 500.
  - Pydantic schemas check syntax only. A message raised in a Pydantic validator becomes the generic "Valor inválido.", so `FUTURE_DATE`, `CONTRACT_MATURED` and too-many-decimals checks belong in the service.
  - Routers never raise `HTTPException`: its `detail` is replaced by a generic one.
- **Logging** uses the stdlib `logging` module: no prints and no secrets.
  - Each module logs through its own `logger = logging.getLogger(__name__)`. Configuration is set once, at process startup; a logger is never injected or passed as an argument.
- **Style:** ruff (lint + format). Use explicit names. A comment cites the spec section only where the reason is not obvious.

## Tests

- Calculators and accounting are written test first (skill `tdd`), from the cases in spec §13 and the formulas in spec §4, §7 and §8.
- Integration tests run against PostgreSQL 16, in your worktree's own database. Concurrency, outbox and queue-take tests use real connections.
- `tests/architecture/` enforces the module boundaries. The full rule list is in `tests/architecture/boundaries.py`:
  - only `public.py` is imported across modules, and also by `workers/`. A module's `__init__.py` imports nothing;
  - `domain/` uses only the standard library, `di1.shared` and its own domain. It imports no side-effect module (filesystem, network, database, environment, process, concurrency, logging, OS entropy) and calls no clock, random-id, I/O builtin or hidden-generator function. Only seeded or injected random generators are allowed;
  - layers point inwards: `application/` never imports its `infrastructure/` or `presentation/`; `presentation/` never imports `infrastructure/`; `public.py` exposes neither;
  - FastAPI only in `presentation/`, the module's `dependencies.py` (its dependency providers), `composition/` and `main.py`;
  - SQL only in `infrastructure/`, `dependencies.py`, `platform/` and `composition/`;
  - Pydantic only in `presentation/` and `platform/`;
  - modules use only the outbox and envelope parts of `platform.messaging`, and `presentation/messaging/` may also use its consumer base. aio-pika appears only in `platform/` and `workers/`;
  - no dynamic imports. Every file sits in the plan §1 layout: `infrastructure/` may hold any adapter, and `presentation/` holds `http/` and `messaging/`.
- API tests use FastAPI's `TestClient`, which needs `httpx2`. Async tests run under pytest-asyncio in `auto` mode; do not use the `anyio` marker.
- Time-based behaviour (queue order, today's date) uses an injected clock, never the wall clock.

## Commands (from `backend/`)

The full suite is `make test-backend` from the repository root (`scripts/test-backend.sh`): it starts throwaway `postgres:16` and `rabbitmq:4.1-management` containers on free ports (or uses `TEST_DATABASE_URL` / `TEST_RABBITMQ_URL`), sets `REQUIRE_DATABASE_TESTS=1` and `REQUIRE_BROKER_TESTS=1`, and so never skips a database or broker test (README, Setup). Bare `uv run pytest` is for quick local runs:

```bash
uv sync
uv run pytest -q                # bare run only: database tests are skipped (reported, not verified) without TEST_DATABASE_URL
TEST_DATABASE_URL=postgresql+psycopg://postgres:x@localhost:55432/postgres uv run pytest -q
                                # adds the integration tests; each test creates and drops its own database
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests migrations
DATABASE_URL=postgresql+psycopg://…/<your db> uv run alembic upgrade head    # integrator owns migrations/
```

Downgrade is for throwaway databases only: it refuses while business data exists unless `-x allow_data_loss=true` is given. An async test that migrates its database passes its connection through `connection.run_sync` and `config.attributes["connection"]` (see `migrations/env.py`), and never calls `command.upgrade` straight from the event loop. CI sets `REQUIRE_DATABASE_TESTS=1`, so a missing database fails the run instead of skipping.

A test PostgreSQL 16 for your worktree: `docker run -d --name di1-test-db-<lane> -e POSTGRES_PASSWORD=x -p <port>:5432 postgres:16`, with a port of your own.
