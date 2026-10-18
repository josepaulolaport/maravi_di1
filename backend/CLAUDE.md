# Backend rules (loaded when you work in backend/)

These rules add to the root CLAUDE.md. The authorities are:
- `docs/interfaces.md`: contracts, transactions, endpoints;
- `docs/schema.md` / `docs/schema.sql`: the database;
- `docs/maravi_implementation_plan.md` §1: the layout.

## Layout (plan §1)

```text
backend/
  pyproject.toml  uv.lock  alembic.ini
  migrations/{env.py, versions/}        # integrator (X) only
  src/di1/
    main.py                              # integrator
    composition/{routers,dependencies,consumers}.py   # integrator
    platform/{config.py, database/, messaging/, observability/}   # lane H
    contracts/                           # only DTOs that are genuinely shared; integrator
    modules/<module>/                    # lanes A–G
      public.py
      dependencies.py                    # if needed
      domain/
      application/services/
      application/interfaces/            # only when meaningful
      infrastructure/persistence/{models.py, repositories.py, queries/}
      presentation/http/{router.py, schemas.py}
    workers/{main.py, dispatcher.py, outbox_relay.py}   # lane H
  tests/{unit/<module>/, integration/, architecture/, e2e/}
```

Create only the files and packages that are used. Only Processing has a messaging consumer.

## Python rules

- **Typing and data:**
  - Full type hints.
  - Domain values are frozen dataclasses.
  - Pydantic v2 is used only in `presentation/http/schemas.py`.
  - Decimal fields cross HTTP as strings.
- **Calculators** (`pricing`, `pnl`, portfolio accounting) are pure, synchronous and deterministic. They take no session, broker, clock or FastAPI dependency.
- **Services:**
  - Services and HTTP may be `async`.
  - A write receives the Unit of Work (`*, uow`) and saves the fact and the invalidation (`FinancialResultInvalidator`) in the same session, then commits once.
  - A write never enqueues processing.
- **Persistence:**
  - The ORM models mirror `docs/schema.sql` exactly; do not invent columns. A schema change needs the user's decision first (`spec-gap`).
  - Repositories map rows to DTOs and hold no business rules.
  - Never expose an ORM type across modules.
- **Decimal:**
  - Construct from `str`, never from `float`.
  - Fractional powers use `Decimal ** Decimal`; never `math.pow` or a float exponent.
  - Quantize only where an answered precision decision says (OQ-3 is open until then).
- **Messaging:**
  - RabbitMQ delivery is at least once. Handlers are idempotent through `platform.inbox_messages`.
  - Acknowledge only after the durable state change is committed.
  - Publish only through `platform.outbox_messages` and the relay.
- **Logging** uses the stdlib `logging` module: no prints and no secrets.
- **Style:** ruff (lint + format). Use explicit names. A comment cites the spec section only where the reason is not obvious.

## Tests

- Calculators and accounting are written test first (skill `tdd`), from the cases in spec §13 and the formulas in spec §4, §7 and §8.
- Integration tests run against PostgreSQL 16, in your worktree's own database. Concurrency, outbox and dispatch tests use real connections.
- `tests/architecture/` enforces the module boundaries:
  - only `public.py` is imported across modules;
  - no FastAPI outside `presentation` and `composition`;
  - no DB or messaging in `domain`.
- Time-based behaviour (leases, queue order) uses an injected clock, never the wall clock.

## Commands (from `backend/`)

The integrator fixes these commands in Wave 0. Until the scaffold exists, they are the expected set:

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests           # type checks (plan §0: ruff, pytest, optional mypy/pyright)
uv run alembic upgrade head     # against your worktree's database
```
