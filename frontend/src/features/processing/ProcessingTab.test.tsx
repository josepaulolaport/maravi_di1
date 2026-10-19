import {
  act,
  type BoundFunctions,
  type queries,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { ProcessingRequest } from '@/api/contract';
import { db } from '@/api/mocks/db';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

import { isFinal } from './jobStatus';

// Expected values come from the fixture scenario (src/api/mocks/fixtures.ts): five finished
// runs (FAILED 01–05/10 on its first date, CANCELLED 10–12/10 before its first date, COMPLETED
// 14–15/10, CANCELLED 14–16/10 after committing 14 and 15/10, COMPLETED_WITH_ISSUES 14–16/10);
// entries start on 14/10; 14/10 and 15/10 are processed for both chains; on 16/10 cash is
// processed and positions processed with issues; 17/10 and 18/10 are not processed. Each run
// publishes date by date (OQ-23).

const PAGE = '/central-de-controle?tab=processamentos';

/**
 * Serves the job list from the mock store without advancing the fake worker (each mock poll
 * advances it one step), except for the polls released with `release(n)`. Counts the polls.
 */
function holdWorker() {
  let released = 0;
  const polls = { count: 0 };
  server.use(
    http.get(url('/processing/requests'), () => {
      polls.count += 1;
      if (released > 0) {
        released -= 1;
        return undefined; // falls through to the mock handler, which advances the worker
      }
      const items = [...db.requests].sort((a, b) => b.created_at.localeCompare(a.created_at));
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
  return {
    polls,
    release: (n = 1) => {
      released += n;
    },
  };
}

function problemResponse(status: number, code: string, message: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: 'Erro', status, errors: [{ code, message, field: null }] },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );
}

/** Counts the enqueue requests; `gate` holds each answer until it resolves. */
function countEnqueues(gate?: Promise<void>) {
  const posts = { count: 0 };
  server.use(
    http.post(url('/processing/requests'), async () => {
      posts.count += 1;
      if (gate) await gate;
      return undefined;
    }),
  );
  return posts;
}

function countIssueReads() {
  const reads = { count: 0 };
  server.use(
    http.get(url('/processing/issues'), () => {
      reads.count += 1;
      return undefined;
    }),
  );
  return reads;
}

const SEEDED_ID = 'aa000000-0000-4000-8000-000000000001';

/** Adds a job to the mock store (newest of all). */
function seedJob(changes: Partial<ProcessingRequest>): ProcessingRequest {
  const job: ProcessingRequest = {
    id: SEEDED_ID,
    scope: 'ALL',
    start_date: '2026-10-17',
    end_date: '2026-10-18',
    status: 'QUEUED',
    progress_date: null,
    error_code: null,
    error_message: null,
    failed_date: null,
    failed_chain: null,
    created_at: '2026-10-18T10:00:00-03:00',
    updated_at: '2026-10-18T10:00:00-03:00',
    dispatched_at: null,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
    ...changes,
  };
  db.requests.push(job);
  return job;
}

const RUNNING = {
  status: 'RUNNING',
  dispatched_at: '2026-10-18T10:00:01-03:00',
  started_at: '2026-10-18T10:00:02-03:00',
  // 17/10 committed; 18/10 is being processed (OQ-23).
  progress_date: '2026-10-17',
} as const;

function field(scope: BoundFunctions<typeof queries>, label: string) {
  return within(scope.getByRole('group', { name: label }));
}

function history() {
  return within(screen.getByRole('region', { name: 'Histórico de processamentos' }));
}

function jobRow(period: string, status: string) {
  const row = history()
    .getAllByRole('row')
    .find((r) => r.textContent.includes(period) && r.textContent.includes(status));
  if (!row) throw new Error(`no row ${period} ${status}`);
  return within(row);
}

/** `timeout` covers a poll (every 2 s) when the job must move on first. */
async function findJobRow(period: string, status: string, timeout = 1_000) {
  await waitFor(() => jobRow(period, status), { timeout });
  return jobRow(period, status);
}

async function closeMenu(user: ReturnType<typeof renderApp>['user']) {
  await user.keyboard('{Escape}');
  await waitFor(() => {
    expect(screen.queryByRole('menu')).toBeNull();
  });
}

async function openMenu(
  user: ReturnType<typeof renderApp>['user'],
  period: string,
  status: string,
) {
  const row = await findJobRow(period, status);
  await user.click(row.getByRole('button', { name: /Ações do processamento/ }));
  await screen.findAllByRole('menuitem');
  return screen.getByRole('menu');
}

async function typeRange(
  user: ReturnType<typeof renderApp>['user'],
  start: string,
  end: string,
  scope = within(document.body),
) {
  const first = scope.getByRole('textbox', { name: 'Data inicial' });
  const last = scope.getByRole('textbox', { name: 'Data final' });
  await user.clear(first);
  await user.type(first, start);
  await user.clear(last);
  await user.type(last, end);
}

describe('Processamentos: request (§11.1, OQ-20)', () => {
  it('§11.1 keeps the request button disabled until the range is complete and ordered', async () => {
    const { user } = renderApp(PAGE);

    const button = await screen.findByRole('button', { name: 'Solicitar processamento' });
    expect(button).toBeDisabled();
    expect(
      screen.getByText(
        'Intervalo inclusivo. A dependência do fechamento anterior será validada antes da confirmação.',
      ),
    ).toBeInTheDocument();

    await typeRange(user, '18/10/2026', '17/10/2026');
    expect(
      await screen.findByText('A data inicial deve ser anterior ou igual à data final.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveAccessibleDescription(
      'A data inicial deve ser anterior ou igual à data final.',
    );
    expect(button).toBeDisabled();

    await typeRange(user, '17/10/2026', '18/10/2026');
    expect(
      screen.queryByText('A data inicial deve ser anterior ou igual à data final.'),
    ).not.toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it('§11.1 prefills the range from ?inicio= and ?fim= (link from Carteira)', async () => {
    renderApp(`${PAGE}&inicio=2026-10-16&fim=2026-10-18`);

    expect(await screen.findByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveValue('18/10/2026');
    expect(screen.getByRole('button', { name: 'Solicitar processamento' })).toBeEnabled();
  });

  it('OQ-14 ignores a future date in the link', async () => {
    renderApp(`${PAGE}&inicio=2026-10-16&fim=2099-01-01`);

    expect(await screen.findByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveValue('');
  });

  it('OQ-11 previews a range starting on the first entry as starting from the zero state', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    expect(await modal.findByText('14/10/2026 a 16/10/2026')).toBeInTheDocument();
    expect(modal.getByText('3')).toBeInTheDocument();
    expect(field(modal, 'Escopo').getByText('Tudo')).toBeInTheDocument();
    for (const label of ['Estado anterior do caixa', 'Estado anterior das posições']) {
      expect(
        field(modal, label).getByText('Estado inicial (sem lançamentos anteriores)'),
      ).toBeInTheDocument();
    }
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
    expect(modal.queryByText(/período efetivo/i)).not.toBeInTheDocument();
  });

  it("OQ-11 OQ-26 previews a range after a current day with that day's status", async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-15&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    await modal.findByText('15/10/2026 a 16/10/2026');
    expect(
      field(modal, 'Estado anterior do caixa').getByText('Processado (14/10)'),
    ).toBeInTheDocument();
    expect(
      field(modal, 'Estado anterior das posições').getByText('Processado (14/10)'),
    ).toBeInTheDocument();
    expect(modal.getByText('2')).toBeInTheDocument();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-31 a day before processed with issues is enough: no warning', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-17&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    // The fields appear once the preview has loaded.
    await modal.findByText('17/10/2026 a 18/10/2026');
    expect(
      field(modal, 'Estado anterior das posições').getByText('Processado com pendências (16/10)'),
    ).toBeInTheDocument();
    expect(
      field(modal, 'Estado anterior do caixa').getByText('Processado (16/10)'),
    ).toBeInTheDocument();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-31 after an unprocessed day: warns per chain that the run will fail on its first day', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    // Neither chain has 17/10: one warning each.
    const warnings = await modal.findAllByRole('alert');
    expect(warnings.map((w) => w.textContent)).toEqual([
      'O fechamento do caixa de 17/10/2026 não foi processado. Este processamento falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia. Processe antes um intervalo que inclua esse dia.',
      'O fechamento das posições de 17/10/2026 não foi processado. Este processamento falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia. Processe antes um intervalo que inclua esse dia.',
    ]);
    expect(
      field(modal, 'Estado anterior do caixa').getByText('Não processado'),
    ).toBeInTheDocument();
    expect(modal.getByText('1')).toBeInTheDocument();
  });

  it('OQ-21 the scope defaults to Tudo and Caixa warns only about the cash chain', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-17&fim=2026-10-18`);
    expect(await screen.findByRole('radio', { name: 'Tudo' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Caixa' }));
    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    expect(await modal.findByText('Processado (16/10)')).toBeInTheDocument();
    expect(field(modal, 'Escopo').getByText('Caixa')).toBeInTheDocument();
    expect(modal.queryByRole('group', { name: 'Estado anterior das posições' })).toBeNull();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-21 keeps the scope in the URL (escopo) and prefills it from there', async () => {
    const { user, router } = renderApp(`${PAGE}&escopo=posicoes`);
    expect(await screen.findByRole('radio', { name: 'Posições' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Caixa' }));

    expect(router.state.location.search).toContain('escopo=caixa');
  });

  it('OQ-21 sends the chosen scope and shows it in the history', async () => {
    holdWorker();
    const bodies: unknown[] = [];
    server.use(
      http.post(url('/processing/requests'), async ({ request }) => {
        bodies.push(await request.clone().json());
        return undefined;
      }),
    );
    const { user } = renderApp(`${PAGE}&inicio=2026-10-17&fim=2026-10-18&escopo=caixa`);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirmar processamento' });
    await within(dialog).findByText('17/10/2026 a 18/10/2026');
    await user.click(within(dialog).getByRole('button', { name: 'Confirmar processamento' }));

    const row = await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    expect(row.getByText('Caixa')).toBeInTheDocument();
    expect(bodies).toEqual([{ start_date: '2026-10-17', end_date: '2026-10-18', scope: 'CASH' }]);
  });

  it('§10.1 queues the confirmed range and shows it in the history', async () => {
    holdWorker();
    const { user } = renderApp(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await typeRange(user, '17/10/2026', '18/10/2026');
    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirmar processamento' });
    await within(dialog).findByText('17/10/2026 a 18/10/2026');
    await user.click(within(dialog).getByRole('button', { name: 'Confirmar processamento' }));

    const row = await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    expect(row.getByText('0 / 2 dias')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Confirmar processamento' })).toBeNull();
    });
    expect(screen.getByText('6 processamentos encontrados')).toBeInTheDocument();
  });

  it('§11.1 closes the confirmation with "Cancelar" without queueing', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirmar processamento' });
    await within(dialog).findByText('3');
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Confirmar processamento' })).toBeNull();
    });
    expect(screen.getByText('5 processamentos encontrados')).toBeInTheDocument();
    expect(db.requests).toHaveLength(5);
  });
});

describe('Processamentos: request safety (§10.2, OQ-15)', () => {
  async function openConfirmation(user: ReturnType<typeof renderApp>['user']) {
    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirmar processamento' });
    await within(dialog).findByText('3');
    return within(dialog);
  }

  it('§10.2 queues one job on a double click', async () => {
    holdWorker();
    const posts = countEnqueues();
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    const dialog = await openConfirmation(user);
    await user.dblClick(dialog.getByRole('button', { name: 'Confirmar processamento' }));

    await findJobRow('14/10/2026 a 16/10/2026', 'Na fila');
    expect(posts.count).toBe(1);
    expect(db.requests).toHaveLength(6);
  });

  it('§10.2 keeps the confirmation open while the job is being queued, then allows another', async () => {
    holdWorker();
    let open: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      open = resolve;
    });
    const posts = countEnqueues(gate);
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    let dialog = await openConfirmation(user);
    await user.click(dialog.getByRole('button', { name: 'Confirmar processamento' }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Confirmar processamento' })).toBeInTheDocument();
    open();
    await findJobRow('14/10/2026 a 16/10/2026', 'Na fila');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Confirmar processamento' })).toBeNull();
    });

    dialog = await openConfirmation(user);
    await user.click(dialog.getByRole('button', { name: 'Confirmar processamento' }));
    await waitFor(() => {
      expect(posts.count).toBe(2);
    });
    await waitFor(() => {
      expect(db.requests).toHaveLength(7);
    });
  });

  it('OQ-15 shows the API message when queueing fails, and keeps the confirmation open', async () => {
    server.use(
      http.post(url('/processing/requests'), () =>
        problemResponse(422, 'FUTURE_DATE', 'A data não pode ser posterior a hoje.'),
      ),
    );
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    const dialog = await openConfirmation(user);
    await user.click(dialog.getByRole('button', { name: 'Confirmar processamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'A data não pode ser posterior a hoje.',
    );
    expect(db.requests).toHaveLength(5);
  });
});

describe('Processamentos: preview failure (OQ-15)', () => {
  it('OQ-15 shows the API message when the preview fails, and cannot confirm', async () => {
    server.use(
      http.get(url('/processing/preview'), () =>
        problemResponse(422, 'FUTURE_DATE', 'A data não pode ser posterior a hoje.'),
      ),
    );
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Confirmar processamento' })).toBeDisabled();
  });
});

describe('Processamentos: history (§11.1, §10.3)', () => {
  it('§10.3 lists every job with its period, progress and pt-BR status', async () => {
    renderApp(PAGE);

    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');
    const headers = history()
      .getAllByRole('columnheader')
      .map((th) => th.textContent);
    expect(headers.slice(0, 5)).toEqual([
      'Processamento',
      'Período',
      'Escopo',
      'Progresso',
      'Status',
    ]);
    // Days committed, from the range and progress_date (OQ-23).
    expect(jobRow('01/10/2026 a 05/10/2026', 'Falhou').getByText('0 / 5 dias')).toBeVisible();
    expect(jobRow('10/10/2026 a 12/10/2026', 'Cancelado').getByText('0 / 3 dias')).toBeVisible();
    expect(jobRow('14/10/2026 a 15/10/2026', 'Concluído').getByText('2 / 2 dias')).toBeVisible();
    expect(jobRow('14/10/2026 a 16/10/2026', 'Cancelado').getByText('2 / 3 dias')).toBeVisible();
    expect(history().queryByText('Obsoleto')).not.toBeInTheDocument();
    expect(
      jobRow('14/10/2026 a 16/10/2026', 'Concluído com pendências').getByText('7f3c9a02'),
    ).toBeVisible();
    expect(screen.getByText('5 processamentos encontrados')).toBeInTheDocument();
    expect(history().queryByText('Motivo')).not.toBeInTheDocument();
  });

  it('§11.1 filters the history', async () => {
    const { user } = renderApp(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    const search = screen.getByRole('textbox', { name: 'Buscar processamento' });
    expect(search).toHaveAttribute('placeholder', 'Buscar processamento...');
    await user.type(search, 'falhou');

    expect(await screen.findByText('1 processamento encontrado')).toBeInTheDocument();
    expect(history().queryByText('Concluído')).not.toBeInTheDocument();
  });

  it('§11.1 says when there is no job', async () => {
    server.use(
      http.get(url('/processing/requests'), () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );
    renderApp(PAGE);

    expect(await screen.findByText('Nenhum processamento encontrado.')).toBeInTheDocument();
    expect(screen.getByText('0 processamentos encontrados')).toBeInTheDocument();
  });

  it('P21 reads the history page by page: "Carregar mais" asks for the next cursor', async () => {
    const seen: string[] = [];
    server.use(
      http.get(url('/processing/requests'), ({ request }) => {
        const params = new URL(request.url).searchParams;
        seen.push(params.toString());
        // Final jobs only, so nothing is polled: every request below is one the test caused.
        const jobs = [...db.requests]
          .filter((job) => isFinal(job.status))
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
        return params.get('cursor') === 'page-2'
          ? HttpResponse.json({ items: jobs.slice(2), next_cursor: null })
          : HttpResponse.json({ items: jobs.slice(0, 2), next_cursor: 'page-2' });
      }),
    );
    const { user } = renderApp(PAGE);

    expect(await screen.findByText('2 processamentos exibidos')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }));

    const total = db.requests.filter((job) => isFinal(job.status)).length;
    expect(await screen.findByText(`${total} processamentos encontrados`)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Carregar mais' })).not.toBeInTheDocument();
    // Older finished jobs from page 2 are history, not news: no "job finished" refresh rereads
    // the pages (review finding, PR for frontend/contract-review).
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(seen).toEqual(['limit=20', 'limit=20&cursor=page-2']);
  });

  it('P21 a search with no match among the loaded jobs points to "Carregar mais"', async () => {
    server.use(
      http.get(url('/processing/requests'), () => {
        const jobs = [...db.requests]
          .filter((job) => isFinal(job.status))
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
        return HttpResponse.json({ items: jobs.slice(0, 2), next_cursor: 'page-2' });
      }),
    );
    const { user } = renderApp(PAGE);
    await screen.findByText('2 processamentos exibidos');

    await user.type(screen.getByRole('textbox', { name: 'Buscar processamento' }), 'falhou');

    expect(
      await screen.findByText(
        'Nenhum processamento entre os exibidos. Use “Carregar mais” para buscar nos anteriores.',
      ),
    ).toBeInTheDocument();
  });

  it('OQ-20 offers only the actions each status allows', async () => {
    seedJob({});
    seedJob({
      ...RUNNING,
      id: 'aa000000-0000-4000-8000-000000000002',
      start_date: '2026-10-15',
      status: 'CANCELLING',
      created_at: '2026-10-18T09:00:00-03:00',
      cancel_requested_at: '2026-10-18T10:05:00-03:00',
    });
    holdWorker();
    const { user } = renderApp(PAGE);

    let menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Cancelar processamento',
    ]);
    await closeMenu(user);

    menu = within(await openMenu(user, '15/10/2026 a 18/10/2026', 'Cancelando'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Ver detalhes']);
    await closeMenu(user);

    menu = within(await openMenu(user, '14/10/2026 a 15/10/2026', 'Concluído'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Ver detalhes']);
    await closeMenu(user);

    menu = within(await openMenu(user, '14/10/2026 a 16/10/2026', 'Cancelado'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Solicitar novo processamento',
    ]);
  });

  it('OQ-23 a new request for a cancelled run starts at the first date it did not reach', async () => {
    const { user, router } = renderApp(PAGE);

    // Cancelled after committing 14/10 and 15/10: what is left is 16/10.
    const menu = within(await openMenu(user, '14/10/2026 a 16/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Solicitar novo processamento' }));

    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-16&fim=2026-10-16&escopo=tudo',
    );
  });

  it('OQ-20 OQ-21 OQ-23 prefills a new request from the failed date, with the scope of the run', async () => {
    const failed = db.requests.find((job) => job.status === 'FAILED');
    if (failed) failed.scope = 'CASH';
    const { user, router } = renderApp(PAGE);

    const menu = within(await openMenu(user, '01/10/2026 a 05/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Solicitar novo processamento' }));

    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-01&fim=2026-10-05&escopo=caixa',
    );
    expect(screen.getByRole('radio', { name: 'Caixa' })).toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('01/10/2026');
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveValue('05/10/2026');
  });
});

describe('Processamentos: polling (§11.1, §12)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§12 does not poll when no job is active', async () => {
    const worker = holdWorker();
    renderApp(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');
    const before = worker.polls.count;

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(worker.polls.count).toBe(before);
  });

  it('§12 polls every 2 s while a job is active, and stops once it has finished', async () => {
    seedJob({});
    const worker = holdWorker();
    const issueReads = countIssueReads();
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    const before = worker.polls.count;

    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(worker.polls.count).toBe(before + 1);

    // QUEUED → DISPATCHED → RUNNING (17/10) → RUNNING (18/10) → COMPLETED_WITH_ISSUES.
    worker.release(4);
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', 'Enviado');
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    const running = await findJobRow('17/10/2026 a 18/10/2026', 'Processando');
    expect(running.getByText('0 / 2 dias')).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', '1 / 2 dias');
    const issuesBefore = issueReads.count;
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', 'Concluído com pendências');

    // The finished job refreshes the published results and the pendências once.
    await waitFor(() => {
      expect(issueReads.count).toBe(issuesBefore + 1);
    });
    const afterFinish = worker.polls.count;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(worker.polls.count).toBe(afterFinish);
    expect(issueReads.count).toBe(issuesBefore + 1);
  });
});

describe('Processamentos: a job that finished between two reads (§10.4)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 refreshes the results when a new job is first seen already finished', async () => {
    seedJob({});
    holdWorker();
    const issueReads = countIssueReads();
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    await waitFor(() => {
      expect(issueReads.count).toBeGreaterThan(0);
    });
    const before = issueReads.count;

    // Queued and finished elsewhere between two polls.
    seedJob({
      id: 'bb000000-0000-4000-8000-000000000001',
      start_date: '2026-10-15',
      end_date: '2026-10-15',
      status: 'COMPLETED',
      created_at: '2026-10-18T11:00:00-03:00',
      progress_date: '2026-10-15',
    });
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await findJobRow('15/10/2026 a 15/10/2026', 'Concluído');
    await waitFor(() => {
      expect(issueReads.count).toBe(before + 1);
    });
  });
});

describe('Processamentos: cancel (§10.2)', () => {
  it('§10.2 cancels a queued job at once, after confirmation', async () => {
    seedJob({});
    holdWorker();
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));

    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    expect(dialog.getByText('aa000000')).toBeInTheDocument();
    expect(dialog.getByText('17/10/2026 a 18/10/2026')).toBeInTheDocument();
    expect(dialog.getByText('0 / 2 dias')).toBeInTheDocument();
    expect(dialog.getByText('Na fila')).toBeInTheDocument();
    expect(
      dialog.getByText(
        'O processamento será interrompido ao fim da data em andamento. As datas já processadas continuam publicadas; as seguintes não serão processadas.',
      ),
    ).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Cancelar processamento?' })).toBeNull();
    });
  });

  it('§10.2 goes back without cancelling', async () => {
    seedJob({});
    holdWorker();
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Voltar' }));

    expect(db.requests.find((r) => r.id === SEEDED_ID)?.status).toBe('QUEUED');
  });

  it('§10.2 OQ-23 cancels a running job cooperatively: Cancelando, then Cancelado', async () => {
    // On 17/10 of 17–18/10: the current date commits, 18/10 is not processed. (A cancel during
    // the last date would let the run complete, OQ-26 item 9.)
    seedJob({ ...RUNNING, progress_date: null });
    const worker = holdWorker();
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelando');
    worker.release(1);
    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado', 3_000);
  }, 10_000);

  it('OQ-15 shows the 409 message when the job can no longer be cancelled', async () => {
    seedJob({});
    holdWorker();
    server.use(
      http.post(url('/processing/requests/:id/cancel'), () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Conflito',
            status: 409,
            errors: [
              {
                code: 'JOB_NOT_CANCELLABLE',
                message: 'Este processamento já foi encerrado e não pode ser cancelado.',
                field: null,
              },
            ],
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'Este processamento já foi encerrado e não pode ser cancelado.',
    );
  });
});

describe('Processamentos: details (§11.1, §10.4)', () => {
  it('§10.2 from the details, "Cancelar processamento" moves the focus into the cancel dialog', async () => {
    holdWorker();
    seedJob(RUNNING);
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const details = within(
      await screen.findByRole('dialog', { name: 'Detalhes do processamento' }),
    );
    await user.click(details.getByRole('button', { name: 'Cancelar processamento' }));

    const cancel = await screen.findByRole('dialog', { name: 'Cancelar processamento?' });
    await waitFor(() => {
      expect(cancel).toContainElement(document.activeElement as HTMLElement);
    });
  });

  it('§11.1 OQ-23 shows a failed run: times in Brasília, days, the date it failed on, its error', async () => {
    const { user, router } = renderApp(PAGE);

    const menu = within(await openMenu(user, '01/10/2026 a 05/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Falhou');
    expect(modal.getByText('7f3c9a04')).toBeInTheDocument();
    const field = (label: string) => within(modal.getByRole('group', { name: label }));
    expect(field('Período solicitado').getByText('01/10/2026 a 05/10/2026')).toBeInTheDocument();
    expect(field('Criação').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Início').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Finalização').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Total de dias').getByText('5')).toBeInTheDocument();
    expect(field('Dias concluídos').getByText('0')).toBeInTheDocument();
    expect(field('Dias restantes').getByText('5')).toBeInTheDocument();
    expect(field('Data com erro').getByText('01/10/2026')).toBeInTheDocument();
    expect(modal.getByRole('alert')).toHaveTextContent(
      'Falha inesperada ao gravar os resultados de 01/10/2026. Tente novamente.',
    );
    expect(
      modal.getByText(
        'Nenhuma data deste processamento foi publicada; os resultados anteriores permanecem inalterados.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByRole('progressbar')).not.toBeInTheDocument();

    await user.click(modal.getByRole('button', { name: 'Solicitar novo processamento' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-01&fim=2026-10-05&escopo=tudo',
    );
  });

  it('OQ-23 says a run cancelled before its first date published nothing', async () => {
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '10/10/2026 a 12/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(
      modal.getByText(
        'Nenhuma data deste processamento foi publicada; os resultados anteriores permanecem inalterados.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-23 says which dates a run cancelled midway kept, and offers a new request', async () => {
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '14/10/2026 a 16/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Cancelado');
    expect(field(modal, 'Finalização').getByText('16/10/2026 17:31')).toBeInTheDocument();
    expect(field(modal, 'Dias concluídos').getByText('2')).toBeInTheDocument();
    expect(
      modal.getByText(
        'As datas de 14/10/2026 a 15/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Solicitar novo processamento' })).toBeInTheDocument();
  });

  it('§11.1 still shows an error box for a failed job without a message', async () => {
    seedJob({
      status: 'FAILED',
      error_code: 'UNEXPECTED_ERROR',
      finished_at: '2026-10-18T10:01:00-03:00',
    });
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Falha técnica inesperada.');
  });

  it('§11.1 shows a completed job without the unpublished notice or actions', async () => {
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '14/10/2026 a 15/10/2026', 'Concluído'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Concluído');
    expect(modal.queryByText(/Nenhum dia deste processamento/)).not.toBeInTheDocument();
    expect(
      modal.queryByRole('button', { name: /Solicitar novo|Cancelar/ }),
    ).not.toBeInTheDocument();
  });

  it('§10.4 follows a running job: the date being processed, progress and the cancel actions', async () => {
    seedJob({ ...RUNNING, created_at: '2026-10-18T09:58:00-03:00' });
    holdWorker();
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    const field = (label: string) => within(modal.getByRole('group', { name: label }));
    expect(field('Data em processamento').getByText('18/10/2026')).toBeInTheDocument();
    expect(field('Criação').getByText('18/10/2026 09:58')).toBeInTheDocument();
    expect(field('Início').getByText('18/10/2026 10:00')).toBeInTheDocument();
    expect(field('Finalização').getByText('—')).toBeInTheDocument();
    expect(field('Dias restantes').getByText('1')).toBeInTheDocument();
    expect(modal.getByRole('progressbar', { name: 'Progresso' })).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Cancelar processamento' })).toBeInTheDocument();
    // OQ-30: there is no cancel-and-replace.
    expect(modal.queryByRole('button', { name: /criar novo/ })).not.toBeInTheDocument();
  });
});
