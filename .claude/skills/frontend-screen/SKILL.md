---
name: frontend-screen
description: Build or change a Maravi DI1 screen or component (React, TypeScript, Mantine, TanStack Query, MSW) from the Aura Build designs and the business specification — pt-BR texts, Brazilian formatting, every data/job state, tests. Use for any work under frontend/src.
---

# Build a screen

## 1. Read the specification

- **The screen's section** in `docs/maravi_business_specification.md`:
  - §11.1: Central de Controle;
  - §11.2: Ativos;
  - §11.3: Lançamentos;
  - §11.4: Carteira.
- **The API rules** in §12.
- **The design** in Figma (`frontend/CLAUDE.md` "Designs"), if one exists.
- **The endpoints** in `docs/interfaces.md`, "HTTP endpoints".
- If a text, column, state or behaviour is not specified, use `spec-gap`. Do not invent product behaviour.

## 2. Tests first (Vitest + Testing Library + MSW)

- Put the spec section in each test title.
- The MSW handlers and fixtures follow the endpoint contracts.
- Cover:
  - loading and empty;
  - valid, missing/incomplete, stale and unprocessed data;
  - `COMPLETED_WITH_ISSUES`;
  - every job status;
  - cancel, and cancel and replace;
  - `null` shown as unavailable;
  - the exact pt-BR formatted strings.

See them fail first.

## 3. Build

- Put the query and mutation hooks in the feature folder. Query keys include the date, and mutations invalidate the related queries.
- Poll a job's status only while it is queued or running.
- Format from decimal strings with `Intl.NumberFormat('pt-BR', …)`. Never use `parseFloat`, `toFixed` or `Math.round` on money.
- The browser never calculates. Calculator previews call the pricing endpoint.
- Every input has a label, and colour is never the only signal.

## 4. Verify

Run lint, the type check and the tests. Finish with `pr-ready`.
