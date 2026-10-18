# Frontend rules (loaded when you work in frontend/)

These rules add to the root CLAUDE.md. The authorities are:
- `docs/maravi_business_specification.md` §11–§12: screens and API rules;
- `docs/interfaces.md` "HTTP endpoints".

## Designs

The Aura Build designs are the visual base, and the screens implement them; they are not rebuilt as a separate demo (spec §11). The designs live in **Figma**; nothing is in the repository.

- **Access** is through Figma's official Claude Code plugin (`figma@claude-plugins-official`, installed at user scope, remote server `https://mcp.figma.com/mcp`). Before the first use, run `/mcp` in the session, select figma and authenticate in the browser; `/mcp` again confirms the connection.
- **The file link is given in the session prompt.** Read frames, components and variables through the MCP tools, and take spacing, colours and typography from the design, mapped onto Mantine theme tokens.
- When a screen has no design in Figma, raise a `spec-gap` and do not invent one. When the design and the spec disagree (a column, a figure or a state), **the user decides which is right**. Follow neither silently: stop that part, raise a `spec-gap` that quotes both (spec section and Figma frame) with your recommendation, and keep building the parts that do not depend on it.

## Stack and layout (plan §0–§1)

The toolchain is locked (user, 2026-10-18). Do not add other libraries without the integrator's approval:

| Need | Choice |
|---|---|
| Build and dev server | Vite (React + TypeScript template) |
| Language | TypeScript, `strict: true` |
| Routing | React Router |
| UI components | Mantine: `@mantine/core`, `hooks`, `form` (forms and validation), `dates` (with `dayjs`), `notifications`, `charts` (the cumulative P&L chart) |
| Icons | `@tabler/icons-react` |
| Server state | TanStack Query |
| API mocks | MSW, in the browser during development and in the tests |
| Tests | Vitest, Testing Library (`react`, `user-event`), jsdom |
| Lint and format | ESLint (flat config, typescript-eslint, react-hooks) and Prettier |
| Runtime | Node 24 LTS with npm. `package-lock.json` is committed; `npm ci` installs it |

Each package is the current stable major published before 2026-10-04, the same cut-off as the backend.

**API types.** Until the backend serves them, `frontend/src/api/` holds hand-written response types and MSW fixtures: a **draft contract** derived from the spec and the Figma. Every field not named in the docs is listed as a contract proposal in the PR. The integrator reconciles the draft with the backend when the endpoint is built. At integration (Wave 5) the hand-written types are replaced by types generated from the backend's OpenAPI with `openapi-typescript` (`npm run gen:api`).

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

## Working rules for the frontend lane

- **Commits are batched.** The user approves every commit, and so does another session at the same time. Make one commit per screen or feature: the scaffold, the API draft, then Carteira, Lançamentos, Ativos and Central de Controle. Each commit is still green and one logical change. Show the user the staged diff before committing.
- **You own `frontend/**` only.** Changes elsewhere go to the integrator, in your report and the PR description:
  - Docker Compose and CI;
  - the docs and `CLAUDE.md`;
  - the backend;
  - a spec gap.

  Never edit those paths, even "just one line".
- **Worktree setup.** Run `npm ci` once in your worktree before the first commit. The pre-commit hook runs eslint, tsc and vitest on staged frontend files as soon as `frontend/package.json` exists, and fails without `node_modules`. Development runs `npm run dev` against MSW; the backend is not needed. The integrator adds the frontend to Docker Compose in W0.6.

## Commands (from `frontend/`)

The scaffold creates these scripts:

```bash
npm ci                 # once per worktree
npm run dev            # Vite dev server, API mocked by MSW
npm test               # Vitest
npm run lint && npm run typecheck
npm run gen:api        # Wave 5: types from the backend OpenAPI (openapi-typescript)
```
