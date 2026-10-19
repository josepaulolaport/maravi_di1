# Frontend rules (loaded when you work in frontend/)

These rules add to the root CLAUDE.md. The authorities are:
- `docs/maravi_business_specification.md` §11–§12: screens and API rules;
- `docs/interfaces.md` "HTTP endpoints".

## Designs

The Aura Build designs are the visual base, and the screens implement them; they are not rebuilt as a separate demo (spec §11). They are **preliminary**: data and behaviour come from the spec, and the look is polished during development. Nothing is in the repository.

- **Figma file:** `https://www.figma.com/design/U1Ob49zAEXWiH9n8XMo1Mz/` (file key `U1Ob49zAEXWiH9n8XMo1Mz`), one page with six frames: Carteira, Ativos − 1 (catalogue), Ativos − 2 (DI1 product), Ativos − 3 (contract DI1F28), Lancamentos, Central de controle (Pendências tab only).
- **Processamentos** has no Figma frame. Its design is the clickable Aura Build HTML of Central de Controle, which the user supplies when asked.
- **Access** is through Figma's official Claude Code plugin (`figma@claude-plugins-official`, installed at user scope, remote server `https://mcp.figma.com/mcp`). Before the first use, run `/mcp` in the session, select figma and authenticate in the browser; `/mcp` again confirms the connection.
- **Calls are limited.** The user's Figma seat has a small monthly MCP quota. Prefer one `get_metadata` and one high-resolution `get_screenshot` of the page, cropped locally per frame, over many per-node calls. The text layers are named "Text", so labels come from screenshots, not metadata.
- Read frames, components and variables through the MCP tools, and take spacing, colours and typography from the design, mapped onto Mantine theme tokens.
- **Design-vs-spec decisions already taken:** OQ-19 and OQ-20 in `docs/open-questions.md`. Follow them; do not re-ask.
- When a screen has no design in Figma or in the Aura Build HTML, raise a `spec-gap` and do not invent one. Drawers and modals without a design are the exception: they are built in the same visual language (OQ-19 item 8). When the design and the spec disagree (a column, a figure or a state), **the user decides which is right**. Follow neither silently: stop that part, raise a `spec-gap` that quotes both (spec section and Figma frame) with your recommendation, and keep building the parts that do not depend on it.

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

Each package is the current stable major published before 2026-10-04, the same cut-off as the backend, pinned to an exact version. One exception: **TypeScript is 6.0.x**, not 7, because typescript-eslint 8.71 supports only `typescript <6.1.0`. Supporting packages of the locked tools are allowed: `@eslint/js`, `globals`, `eslint-config-prettier`, `@testing-library/dom` and `@testing-library/jest-dom`, and `recharts` (peer of `@mantine/charts`).

**API types.** Until the backend serves them, `frontend/src/api/` holds hand-written response types and MSW fixtures: a **draft contract** derived from the spec and the Figma. Every field not named in the docs is listed as a contract proposal in the PR. The integrator reconciles the draft with the backend when the endpoint is built. At integration (Wave 5) the hand-written types are replaced by types generated from the backend's OpenAPI with `openapi-typescript` (`npm run gen:api`).

```text
frontend/src/
  app/          # composition only: providers, theme, routes, paths
  api/          # typed HTTP client, draft contract types, MSW handlers and fixtures (mocks/)
  features/<f>/ # one folder per screen: assets, ledger, prices, portfolio, processing
    <F>Page.tsx #   the route component (lazy-loaded)
    components/ #   components used only by this feature
    hooks/      #   TanStack Query hooks (queries, mutations) and the feature's query keys
  shared/       # cross-feature code: layout/, ui/ (common components), format/ (pt-BR formatting)
  test/         # Vitest setup and render helpers
```

## Architecture

- **Dependencies point inward.** `app` composes `features` and `shared`; a feature may import `api` and `shared`, never another feature. Something two features need moves to `shared`. Import with the `@/` alias across folders, and with relative paths inside one folder.
- **Server state lives in TanStack Query**, nowhere else: no copies in `useState`, no global store. Each feature owns its query keys (a `<feature>Keys` factory in `hooks/`), and every key includes its parameters (date, range, id). Mutations invalidate the keys they affect. React state is only for UI state (open drawer, selected rows, form input); URL state (selected date, range, tab, search) lives in the query string, so a screen can be linked and reloaded.
- **Components are thin.** A page composes; data fetching sits in hooks; formatting sits in `shared/format`. Components receive typed props, not raw responses, when that keeps them reusable.
- **One HTTP client** in `api/` (`fetch`, JSON, problem+json errors turned into a typed error). Components never call `fetch`.
- **Mantine first.** Use Mantine components and props before writing CSS. When CSS is needed, use a CSS module beside the component and Mantine CSS variables (`var(--mantine-color-navy-9)`, `var(--app-…)`). Colours and tokens live only in `app/theme.ts`; no hex value elsewhere.
- **Every screen is lazy-loaded** (`app/routes.tsx`), and vendor code is split into cached chunks (`vite.config.ts`). A route error boundary (`RouteErrorPage`) keeps the app usable when a screen throws.
- **Accessibility:** every control has a pt-BR accessible name; tests query by role and name, as a user would. Colour is never the only signal.
- **Tests** render through `test/render.tsx` (`renderApp(route)`), which uses the real providers and routes, with MSW answering every request (an unmocked request fails the test).

## Screens (spec §11)

- **Central de Controle**, with two tabs:
  - **Pendências:** actionable issues only, with "Definir preço". Only the two issue types of spec §10.3 (OQ-31); a `FAILED` job, including "Dia anterior não processado", is shown in Processamentos, not here (OQ-19). Rows come deduplicated from the API (OQ-37): one per (asset, required price date) for a missing price, so "Definir preço DI1F29 em 16/10" appears once, and one per asset for an expired open position; each row shows its earliest affected date.
  - **Processamentos** (OQ-20):
    - pick a date range and a scope (Caixa, Posições, Tudo; OQ-21) and preview exactly [A, B] (days to process), with the warning when the chain's day before is not processed (nor the zero state), so the run would fail on its first date (OQ-11, OQ-23, OQ-31); the preview returns both chains (`predecessor.cash`, `predecessor.positions`) for every scope, and the screen warns only for the scope's chains (OQ-39); no "período efetivo";
    - queue the job, then follow its progress ("x / y dias") and status;
    - cancel a job; cancelling and queuing a new request are separate actions, with no "Cancelar e criar novo processamento" (OQ-30);
    - publication is per date (OQ-23): a cancelled or failed job keeps the dates it committed, and later dates are untouched; it offers "Solicitar novo processamento", prefilled from the failed date, or the first date not reached, to the original end;
    - the job details show `error_code`/`error_message` on Falhou and also on Concluído com pendências, where they are set when one chain of a Tudo job failed and the other reached the end, and on Cancelado when a Tudo job is cancelled after one chain failed (OQ-36);
    - a Concluído com pendências or Cancelado ALL job where a chain failed also offers "Solicitar novo processamento", prefilled with the failed chain's scope (Caixa or Posições, from `failed_chain`) from `failed_date` to the original end; on Cancelado, the plain retry from the first date not reached stays available too; the job details show `failed_date` and `failed_chain` (OQ-40 items 3 and 6);
    - finished and cancelled jobs stay in the history; no "Motivo" column, no duplicate blocking.
  - No financial KPIs on this screen.
- **Ativos:**
  - Browse type → class → product → instrument, with API data only (OQ-19).
  - The product page lists contracts with their latest reference observation, always next to its date.
  - The contract page lets you enter, inspect and correct a reference price for a date. **There is no rate ↔ PU calculator** (OQ-19).
  - The price calendar shows days without an observation as such; it never interpolates. It has a "Fonte" column (Manual/B3), and the row menu offers Corrigir and Remover; there are no revisions (OQ-25).
- **Lançamentos:**
  - The history of trades and cash movements, with an inclusive date range and search. Trades show both PU and rate.
  - A cash strip: Caixa D0 = published cash on the range's end date, Caixa D−1 = the day before, each with the cash chain's status on that date (OQ-19, OQ-23).
  - One "Novo lançamento" modal for compra, venda, aporte and retirada; one entry list for trades and cash movements (OQ-24).
  - Delete one or many entries, with confirmation. The deletion is permanent, all or nothing, with no reason (OQ-32). No editing.
  - Instrument type and entry type are distinct.
- **Carteira:**
  - One date, showing published data only.
  - KPIs: Saldo em caixa, AUM/Patrimônio, P&L diário, P&L de posições, P&L de operações.
  - A compact cumulative P&L chart that draws every calendar day of the period (OQ-41). It always ends on the selected date; the user picks only its start, which must be before that date (default: the 30 days ending on the date), kept in the URL as `?pnl_start=` and ignored when invalid (OQ-27). It draws each point's `range_cumulative_pnl` from `GET /portfolio/pnl` (the backend's sum of `daily_pnl` from the start date) and never sums; the stored `cumulative_pnl` stays in the KPIs. Series points carry the positions chain's status and processing time only (OQ-31 item 8). The API returns one point per calendar day; on an unprocessed day (`status` `NOT_PROCESSED`, "Não processado"; None in the Python view) or a day whose `daily_pnl` is null, `range_cumulative_pnl` adds 0, so the line is never broken and the chart does not filter points (OQ-41). The day's own P&L diário still shows as unavailable. A day adds its `daily_pnl` only when its positions status is `PROCESSED`/`PROCESSED_WITH_ISSUES` and `daily_pnl` is not null; `FAILED` and `RUNNING` points carry their status with `daily_pnl`, `cumulative_pnl` and `pnl_status` null and `published_at` the stored processing time, and add 0 (OQ-41 item 4). The tooltip shows the day's status ("Não processado", "Erro", "Processando") or "P&L diário indisponível" for a processed day with null `daily_pnl`; the card shows a short pt-BR note when any day in the range is not complete, i.e. adds 0 under item 4 (OQ-41 item 5).
  - The positions table, with the columns of spec §11.4. Its reference PU, rate and source are the current preferred price from the price table (OQ-30), as the API returns them; after a price correction the date shows the new PU next to the old figures and keeps its status until reprocessed (OQ-31).
  - Only two data-status badges, Caixa and Posições, each showing that chain's status on the date (OQ-23) and, when processed, "Processado em dd/mm/aaaa hh:mm" from the chain's processing time (OQ-31), with links to Pendências and Processamentos; no badge per KPI and no incomplete notice cards.
  - Cash is not a position row. No realized or unrealized P&L.

## Rules

- **The backend is the only calculator.** The browser never computes PU, rate, P&L, cash or averages. Forms take PU **or** rate (a toggle and one input); there is no preview for now, and the complementary value appears once the entry is saved (OQ-19). A future preview would call the pricing endpoint.
- **Decimals are strings end to end.** Format them with `Intl.NumberFormat('pt-BR', …)` from the string. Never use `parseFloat` or `Math.round` on money.
- **`null` means unavailable.** Show it as unavailable ("—"), never as `0`.
- **Distinguish the states:** each date has one status per chain (OQ-23, OQ-31): Processado, Processado com pendências, Processando, Erro, Não processado, with "Processado em dd/mm/aaaa hh:mm" when processed; there is no Desatualizado; missing values are `null`, never zero.
- **Job statuses** are shown in Portuguese (spec §10.3, OQ-20): QUEUED Na fila, DISPATCHED Enviado, RUNNING Processando, CANCELLING Cancelando, CANCELLED Cancelado, COMPLETED Concluído, COMPLETED_WITH_ISSUES Concluído com pendências, FAILED Falhou. There is no "Bloqueado" and, since OQ-23, no Obsoleto (SUPERSEDED).
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
