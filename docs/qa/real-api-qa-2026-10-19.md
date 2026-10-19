# Real-API QA of the frontend, 2026-10-19

Read-only QA: every screen of the frontend driven in a browser against the real backend, to find
mismatches between the MSW mocks and the API before delivery. No code was changed.

## Status (added by lane X, 2026-10-19)

- **3 (empty catalogue), fixed** in the lane X final-fixes PR: the Compose `seed` service applies
  `scripts/seed_catalogue.sql` on every `docker compose up`, and it now seeds the DI1 product too.
- **8 (`created_at` offset), fixed** in the same PR: the ledger sends `created_at` in UTC (`Z`), like
  every other module.
- **9 (mixed decimal scales), left as it is, on purpose:** every value is exact and the UI formats them
  all; changing scales would touch every read model shortly before delivery for a cosmetic gain.
- **Frontend findings (1, 2, 4, 5, 6, 7, 10):** handled in a parallel lane I PR; its description says
  which are fixed.
- **Mock dev mode removed (#114, later the same day):** the MSW fake backend and `VITE_API_MOCKS` this
  report compares against no longer exist; MSW now answers the tests only, with static fixtures, and
  the dev server always proxies to the real API. The report below is kept as written.

## Setup

- Code: `origin/main` at `dde3dd6` (worktree `qa-real-api-31390d`).
- Backend: `DI1_API_PORT=18200 DI1_RABBITMQ_MANAGEMENT_PORT=25772 docker compose -p di1-qa up -d --build --wait`,
  then `scripts/seed_catalogue.sql`. All six services up (`api`, `worker`, `outbox-relay`, `postgres`,
  `rabbitmq`; `migrate` exited 0). `/health` → `{"status":"ok"}`.
- Frontend: `VITE_API_MOCKS=false API_PROXY_TARGET=http://127.0.0.1:18200 npm run dev -- --port 5180`
  (Vite 8.3.2). Every `/api/*` request in the browser went through the proxy to the real API (checked in the
  network log; no MSW worker).
- Browser: the desktop app's built-in browser, viewport 1024×768 unless noted (1280 and 1440 for the
  layout checks). Clock: São Paulo, today = 19/10/2026.

## Summary

**No contract mismatch was found.** Every field the screens read exists in the real responses with the
type the mocks use (decimal strings, `null` for unavailable, `{items, next_cursor}` pages, problem+json
errors with `errors[].field`). The challenge example reproduces in the UI exactly: PU 90.909,09, Saldo em
caixa R$ 109.090,91, Patrimônio total R$ 200.000,00, P&L 0, both chains "Processado".

What remains are frontend UX/layout problems and two cosmetic API inconsistencies.

| # | Severity | Screen | Problem | At fault |
|---|---|---|---|---|
| 1 | Medium | Lançamentos | A deletion answered 404 leaves the dialog and the list stale; retrying fails forever | Frontend (backend body could help) |
| 2 | Medium | Carteira | KPI cards clip money at 1024 px; minus sign wraps at 1280 px | Frontend |
| 3 | Low | Ativos | A fresh stack has an empty catalogue and no way in the UI to create the DI1 product | Setup / docs (spec: browse only) |
| 4 | Low | Lançamentos, Carteira, Processamentos | A date after today is silently replaced or blanked; `FUTURE_DATE` never reaches the user | Frontend |
| 5 | Low | Processamentos | Cancel dialog of a queued run says it stops "ao fim da data em andamento" | Frontend (copy) |
| 6 | Low | Ativos, Lançamentos, Carteira | Rates and PUs shown with 2 decimals only; a rate of −99,9998% shows as "-100,00%" | Frontend / spec silent |
| 7 | Low | Contrato | After "Definir preço" from a Pendência, the calendar period moves and hides the next missing date | Frontend (UX) |
| 8 | Low | API | `created_at` offset differs by module (`-03:00` vs `Z`) | Backend (cosmetic) |
| 9 | Low | API | Decimal scale differs inside one response (`"0"`, `"200000.00"`, `"0.0000000000"`) | Backend (cosmetic) |
| 10 | Cosmetic | Processamentos, charts | Progress text wraps; flat-zero chart has R$ 0–4 axis | Frontend |

## Findings

### 1. Medium: a 404 on deletion leaves Lançamentos stale (frontend)

- **Steps:** Lançamentos, period 10/10/2026, "Carregar mais", "Selecionar todos" (55 entries), "Excluir
  selecionados". Before confirming, delete one of the selected entries elsewhere
  (`POST /api/ledger/entries/deletions {"ids":["59e2f950-…"]}` → 204). Confirm "Excluir".
- **Expected:** OQ-32 / interfaces "Errors": 404 `NOT_FOUND`, nothing deleted — correct on the backend.
  The screen should then let the user recover: refresh the list (the vanished entry is gone) and drop the
  missing id from the selection, or say which entry no longer exists.
- **Actual:** the dialog shows "Lançamento não encontrado." and stays open; the table still lists the
  deleted entry and keeps all 50 selected; "Excluir" fails again with the same 404 every time. Only a page
  reload recovers.
- **Request/response:** `POST /api/ledger/entries/deletions` → 404
  `{"title":"Recurso não encontrado","detail":"Lançamento não encontrado.","errors":[{"code":"NOT_FOUND","message":"Lançamento não encontrado.","field":null}]}`.
  The body does not name the missing id, so the frontend cannot point at it; returning it (e.g. in
  `errors[].field` = `ids` plus the id) would be a contract change for lane X.
- **Fault:** frontend (invalidate the entries query on 404); optionally backend for a more useful body.
- Two concurrent tabs or a second user hit this; in a single-user demo it is unlikely.

### 2. Medium: Carteira KPI cards clip values (frontend)

- **Steps:** Carteira 19/10/2026 after the missing-price scenario (Saldo em caixa R$ 285.347,65), viewport
  1024×768.
- **Expected:** spec §11.4 KPIs readable; values are Brazilian-formatted money.
- **Actual:** at 1024 px the cash card reads "R$ 285.347,6" (cut), "Aportes R$ 200.000," and the operações
  line breaks as "-" / "R$ 90.90…". At 1280 px the value fits but "−R$ 90.909,09" breaks after the minus
  sign. At 1440 px everything fits.
- **Fault:** frontend layout (five equal cards; long values need `nowrap` on the sign+value, a smaller
  font, or wrapping the grid earlier).

### 3. Low: no way to create the DI1 product from the UI (setup/docs)

- **Steps:** fresh `docker compose up` + `seed_catalogue.sql`, open Ativos.
- **Expected:** spec §11.2 only browses `tipo → classe → produto → instrumento`; there is no product form,
  by design. `seed_catalogue.sql` seeds the type and class only.
- **Actual:** Ativos shows "0 produtos encontrados" with nothing to click; "Novo contrato" exists only on a
  product page. The DI1 product had to be created with `POST /api/products` (as `scripts/e2e_smoke.py`
  does).
- **Fault:** not a code bug. For the demo, either seed the DI1 product too or document the one `curl` in
  the README. Raising it because an evaluator following the UI hits a dead end on the first screen.

### 4. Low: future dates are silently replaced, never reported (frontend)

- **Steps and actual:**
  - Novo lançamento → Caixa: typing 20/10/2026 in "Data" reverts to 19/10/2026 on blur, without a message.
  - `/carteira?date=2026-10-20` silently loads 19/10/2026 (URL rewritten).
  - `/central-de-controle?tab=processamentos&inicio=2026-10-19&fim=2026-10-21` leaves "Data final" empty.
- **Expected:** OQ-14/OQ-29/OQ-35: a date after today is rejected with 422 `FUTURE_DATE`. The backend does
  so on every path checked: `POST /ledger/entries` (field `date`), `GET /portfolio/summary` (`date`),
  `GET /portfolio/pnl` (`end_date`), `POST /processing/requests` and `GET /processing/preview`
  (`end_date`), all with "A data não pode ser posterior a hoje.".
- **Fault:** frontend. Guarding is fine, but silently replacing the user's input is not "rejected";
  the user does not learn why the date changed. Show the pt-BR message instead (or at least keep the typed
  value with a field error).

### 5. Low: cancel dialog copy is wrong for a queued run (frontend)

- **Steps:** queue a long run, queue a second (Na fila), open "Cancelar processamento" on the queued one.
- **Expected:** interfaces "Processing": "Cancellation of queued work is immediate: a `QUEUED` run becomes
  `CANCELLED` at once."
- **Actual:** the dialog says "O processamento será interrompido ao fim da data em andamento. As datas já
  processadas continuam publicadas; as seguintes não serão processadas." Behaviour is right (it went to
  Cancelado at once); only the text is for a running job.
- **Fault:** frontend copy; choose the text by status.

### 6. Low: rates and PUs display 2 decimals only (frontend / spec silent)

- **Examples:** reference price PU 99.999.999.999 → API `rate: "-0.999998085813"` shown as **"-100,00%"**,
  which reads as a value the backend forbids ("A taxa deve ser maior que −100%."). Trade PU
  `90909.0909090909` shown as "90.909,09"; average rate `0.100000000000` as "10,00%".
- **Spec:** OQ-3 rounds *money* to 2 dp for display; it says nothing about PU and rate display precision.
- **Fault:** not a contract bug. Recommend 4 dp for rates (DI1 is quoted that way) and keeping the PU at
  2 dp, or deciding it as an OQ.

### 7. Low: "Definir preço" moves the calendar past the next pendência (frontend UX)

- **Steps:** two pendências for DI1QB28 (18/10 and 19/10). "Definir preço" on 18/10 opens the contract
  with `?registrar=2026-10-18`; save PU 88.000.
- **Actual:** the period becomes 19/09–18/10 (`?inicio=2026-09-19&fim=2026-10-18`), so 19/10, the other
  missing date, is no longer in the calendar. The user must go back to Pendências.
- **Expected:** not specified; keeping the previous period (ending today) would be friendlier.

### 8. Low: `created_at` offset differs by module (backend, cosmetic)

- `GET /api/ledger/entries` → `"created_at": "2026-10-19T13:27:39.159943-03:00"`.
- `POST /api/products`, `/api/instruments`, `/api/reference-prices`, `GET /api/processing/requests` →
  `"…Z"` (UTC).
- Both are valid ISO 8601 and the frontend converts both correctly (job details show 13:33 for
  16:33:39Z). Only consistency.

### 9. Low: decimal scale differs within one response (backend, cosmetic)

`GET /api/portfolio/summary?date=2026-10-19` (challenge example):
`"deposits": "200000.00"`, `"withdrawals": "0"`, `"position_pnl": "0"`, `"trades_pnl": "0.0000000000"`,
`"aum": "200000.0000000000"`. Values are right and the UI formats all of them correctly; an evaluator
reading the JSON may notice.

### 10. Cosmetic

- Processamentos: "1.621 / 9.789 dias" wraps onto two lines in the Progresso column.
- Carteira chart with every point at 0 draws a Y axis R$ 0,00 … +R$ 4,00; the price-history chart with a
  single point draws ticks like "99.999.999.997,00".

## Verified working against the real API

- **Ativos:** catalogue tabs from `/instrument-types`; product list; accent-insensitive search
  (`deposito` finds "Depósito", `?busca=` in the URL); product page and contract count; "Novo contrato"
  trims and upper-cases (` di1qa27 ` → `DI1QA27`); duplicate code → field error "Já existe um contrato com
  este código." (422 on `code`); "Último PU" "—" (OQ-33); contract page, 30-day calendar, "Registrar
  preço" by rate (10% → PU 90.909,09, Manual), "Corrigir/Remover" menu, Remover (204, toast "Preço de
  referência removido."); calendar of a matured contract ends at its maturity (§11.2).
- **Lançamentos:** aporte R$ 200.000,00; compra 1 DI1QA27 at 10,00% → PU 90.909,09, valor −R$ 90.909,09;
  list newest first; keyset pagination 50 + "Carregar mais" (58 rows, no duplicate); search (`qa27`,
  `aporte`) and `inicio`/`fim`/`ordem` in the URL; multi-delete of 55 entries after "Carregar mais"
  (204, "55 lançamentos excluídos."); single delete from the row menu; cash strip Caixa D−1/D0 with
  "Processado em …"; "Processar" opens the processing modal prefilled with the period and a correct
  preview. Server field errors show on their field: 2-dp cash, PU 0, rate −100%, PU with 11 dp (all 422
  from the backend, mapped by `errors[].field`).
- **Central de Controle:** preview (days, both predecessors, zero state "Estado inicial (sem lançamentos
  anteriores)", "Processado (17/10)", and the predecessor warning for a gap); queue Tudo; Na fila →
  Concluído, "x / y dias"; details with local times; history keyset pagination 20 + "Carregar mais"
  (23 rows); cancel a queued run → Cancelado at once; cancel a running 9.789-day run → Cancelado with
  "As datas de 01/01/2000 a 18/04/2020 foram publicadas…" and "Solicitar novo processamento"; FAILED run
  with "Data com erro 01/01/2022", "Cadeia com erro Posições", "Dia anterior não processado"
  (`POSITIONS_PREDECESSOR_MISSING`); Concluído com pendências; Pendências deduplicated per
  (asset, price date) with "Definir preço" deep link, and "Contrato vencido com posição aberta" with
  "—" date and "Ver lançamentos".
- **Carteira:** challenge example as above; missing price → "Processado com pendências", Patrimônio
  total "—", P&L diário/posições/acumulado "—", P&L operações R$ 0,00, row badge "SEM PREÇO", AUM null;
  after adding prices and reprocessing: P&L −R$ 200,00, acumulado +R$ 56,74, AUM R$ 200.056,74 (checked by
  hand: −2 × (88.100 − 88.000) = −200; −2 × (88.000 − 88.128,37) = +256,74); matured contract on 16/10:
  PU ref. 0,00, market value R$ 0,00, P&L posições −R$ 100.000,00; `pnl_start` in the URL; the
  incomplete-days note.
- **Backend rules seen through the API:** `FUTURE_DATE` on every read and write above; `INVALID_RANGE`;
  maturity day requires PU (422 "Na data de vencimento informe o PU."); trade and price after maturity
  422 `CONTRACT_MATURED`; quantity 0 rejected; rate ≤ −100% rejected; no invalidation on write (19/10 kept
  its figures after a back-dated trade until reprocessed, OQ-31).

## Not verified

- **"Cancelando":** the worker honours a cancel within about 1 ms (`cancel_requested_at`
  16:35:59.266015Z, `finished_at` 16:35:59.267668Z) and runs about 150 days/s, so no poll ever saw
  `RUNNING` with `cancel_requested_at` set. The label and the second-cancel 409 `JOB_NOT_CANCELLABLE`
  were not exercised through the UI.
- Worker restart/recovery, B3 prices (no B3 input in the UI), chart tooltips, mobile widths, keyboard-only
  use and screen-reader names (the accessibility tree showed some inputs named by their placeholder,
  e.g. "DI1F31", "DD/MM/AAAA"; check with axe before concluding).
- Typing into the native `time` input did not change the prefilled current time in this browser; likely a
  tool limitation, not checked by hand.
