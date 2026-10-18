---
name: add-endpoint
description: Add or change a Maravi DI1 backend HTTP endpoint end to end inside one module — service method, repository/query, Pydantic schemas, router, module dependency provider, tests against PostgreSQL. Use for any change under modules/<m>/presentation/http or a service an endpoint calls.
---

# Add an endpoint

## 1. Contract first

- **Find the endpoint** in `docs/interfaces.md`, "HTTP endpoints", and the service method behind it in the module's contract section.
- **Find its transaction boundary** in `docs/interfaces.md`, "Transaction boundaries", for example a mutation plus invalidation in one UoW.
- **Find the behaviour** in `docs/maravi_business_specification.md`.
- **If the method, path, body, response or error is not specified, stop and use `spec-gap`.** The error shape is OQ-15, and `/portfolio/pnl` is OQ-16.

## 2. Tests first

- **Unit test of the service**, with in-memory fakes of its interfaces:
  - the happy path;
  - each error;
  - for writes, that the invalidator was called in the same UoW and that **nothing was enqueued**.
- **HTTP test against PostgreSQL** in your worktree's database:
  - the request and the full response;
  - decimals as strings;
  - `null` for a missing value, never `0`.

Run them and see them fail.

## 3. Build the layers in your module only

1. **`application/services/`:** the service method. It receives `*, uow` for writes, calls the pure domain code, and commits once.
2. **`infrastructure/persistence/`:**
   - the models mirror `docs/schema.sql` exactly;
   - queries go in `queries/`;
   - repositories return DTOs and hold no rules.
3. **`presentation/http/schemas.py`:** Pydantic v2 schemas, with decimal fields as strings.
4. **`presentation/http/router.py`:** parse the request, call the service, return the response. No business logic.
5. **`dependencies.py`:** the module's own providers.

Router registration and cross-module wiring belong to the integrator (`composition/`). Ask for them in your PR description.

## 4. Verify

Run the module's tests, the integration tests, lint, the type checks and the architecture tests. Finish with `pr-ready`.
