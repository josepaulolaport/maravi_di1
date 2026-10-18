# Frontend rules (loaded when you work in frontend/)

These rules add to the root CLAUDE.md. The authorities are:
- `docs/maravi_business_specification.md` §11–§12: screens and API rules;
- `docs/interfaces.md` "HTTP endpoints".

## Designs

The Aura Build designs are the visual base, and the screens implement them; they are not rebuilt as a separate demo (spec §11). The designs live in **Figma**; the file link is added here once it exists. Nothing is in the repository.

When a screen has no design in Figma, raise a `spec-gap` and do not invent one.

## Stack and layout (plan §1)

React + TypeScript, Mantine, TanStack Query and MSW.

```text
frontend/src/
  features/{assets, ledger, prices, portfolio, processing}/
  api/          # typed client + MSW handlers and fixtures
  shared/       # formatting, layout, common components
```

## Screens (spec §11)

- **Central de Controle**, with two tabs:
  - **Pendências:** actionable issues only, with "Definir preço".
  - **Processamentos:**
    - pick a date range and preview it, including the warning when the state before it is stale (OQ-11);
    - queue the job, then follow its progress and status;
    - cancel a job, or cancel and replace it;
    - finished and cancelled jobs stay in the history.
  - No financial KPIs on this screen.
- **Ativos:**
  - Browse type → class → product → instrument.
  - The contract page has the rate ↔ PU calculator and lets you enter, inspect and correct a reference price for a date.
  - The price calendar shows days without an observation as such; it never interpolates.
- **Lançamentos:**
  - The history of trades and cash movements, with an inclusive date range and search.
  - Drawers for compra, venda, aporte and retirada.
  - Delete one or many entries, with confirmation. No editing.
  - Instrument type and entry type are distinct.
- **Carteira:**
  - One date, showing published data only.
  - KPIs: Saldo em caixa, AUM/Patrimônio, P&L diário, P&L de posições, P&L de operações.
  - A compact cumulative P&L chart, shown only where the history is complete.
  - The positions table, with the columns of spec §11.4.
  - Stale and incomplete markers, with links to Pendências and Processamentos.
  - Cash is not a position row. No realized or unrealized P&L.

## Rules

- **The backend is the only calculator.** The browser never computes PU, rate, P&L, cash or averages. Calculator previews call the pricing endpoint.
- **Decimals are strings end to end.** Format them with `Intl.NumberFormat('pt-BR', …)` from the string. Never use `parseFloat` or `Math.round` on money.
- **`null` means unavailable.** Show it as unavailable ("—"), never as `0`.
- **Distinguish the states:** valid, missing/incomplete, stale, unprocessed and `COMPLETED_WITH_ISSUES` (plan §6).
- **Job statuses** are shown in Portuguese: QUEUED, DISPATCHED, RUNNING, CANCELLING, CANCELLED, COMPLETED, COMPLETED_WITH_ISSUES, FAILED, SUPERSEDED.
- **Polling:** status is polled only while a job is queued or running.
- **All visible text is pt-BR**, with Brazilian number and date formats. Identifiers are English.
- **Mocks:** MSW handlers follow the API contracts in `docs/interfaces.md`. When a contract is wrong, raise it to the integrator; do not freeze a wrong API to keep the mocks (spec §12).
- **Errors** are RFC 9457 problem+json (`docs/interfaces.md` "Errors", OQ-15). Show each `errors[].message` (pt-BR) on its `field` when one is given, and on the page otherwise.

## Tests

- Vitest + Testing Library + MSW. Cover every state above for each screen.
- The test title cites the spec section, e.g. `it('§11.4 shows null P&L as unavailable', …)`.

## Commands (from `frontend/`)

The scaffold fixes these commands. Until it exists, they are the expected set:

```bash
npm ci
npm run dev
npm test
npm run lint && npm run typecheck
```
