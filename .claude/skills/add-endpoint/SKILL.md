---
name: add-endpoint
description: Add or change a Maravi DI1 backend HTTP endpoint end to end inside one module — service method, repository/query, Pydantic schemas, router, module dependency provider, tests against PostgreSQL. Use for any change under modules/<m>/presentation/http or a service an endpoint calls.
---

# Add an endpoint

## 1. Contract first

- **Find the endpoint** in `docs/interfaces.md`, "HTTP endpoints", and the service method behind it in the module's contract section.
- **Find its transaction boundary** in `docs/interfaces.md`, "Transaction boundaries", for example a mutation saved in one UoW, with nothing else (OQ-31).
- **Find the behaviour** in `docs/maravi_business_specification.md`.
- **If the method, path, body, response or error is not specified, stop and use `spec-gap`.** Errors follow `docs/interfaces.md` "Errors" (problem+json and its code catalogue).

## 2. Tests first

- **Unit test of the service**, with in-memory fakes of its interfaces:
  - the happy path;
  - each error;
  - for writes, that only the fact was saved (no date status changed, OQ-31) and that **nothing was enqueued**.
- **HTTP test against PostgreSQL** in your worktree's database:
  - the request and the full response;
  - decimals as strings;
  - `null` for a missing value, never `0`.

Run them and see them fail.

## 3. Build the layers in your module only

1. **`application/services/`:** the service method. The service is built per request on the Unit of Work (`build_<module>_service(uow, ...)`) and keeps it; a write calls the pure domain code and commits once, and no method takes `uow`.
2. **`infrastructure/persistence/`:**
   - the models mirror `docs/schema.sql` exactly;
   - queries go in `queries/`;
   - repositories return DTOs and hold no rules.
3. **`presentation/http/schemas.py`:** Pydantic v2 schemas named `*Request`/`*Response`/`*ListResponse`/`*PageResponse`, each response built by `of(cls, x) -> Self`. Request bodies extend `di1.platform.http.RequestBody` (`extra="forbid"`); decimals are `DecimalString` in, plain strings out; instants are `UtcDatetime`; enums and UUIDs keep their types; database integer ranges are `Field` bounds here.
4. **`presentation/http/router.py`:** `create_router(*, get_service, ...)`, keyword-only, every collaborator through `Depends`; `APIRouter(prefix=..., tags=[...])`, `fastapi.status`, return annotations (no `response_model`). Parse the request, call the service, return the response. No business logic.
5. **`dependencies.py`:** the module's own providers.

Router registration and cross-module wiring belong to the integrator (`composition/`). Ask for them in your PR description.

## 4. Verify

Run the module's tests, the integration tests, lint, the type checks and the architecture tests. Finish with `pr-ready`.
