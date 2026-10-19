import {
  act,
  type BoundFunctions,
  type queries,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type {
  PredecessorState,
  ProcessingPreview,
  ProcessingRequest,
  ProcessingScope,
} from '@/api/contract';
import { job, processingRequests } from '@/test/msw/fixtures';
import { url } from '@/test/msw/handlers';
import { countReads, server, serveJobs } from '@/test/msw/server';
import { renderApp } from '@/test/render';

// The history is the fixtures' five finished runs (src/test/msw/fixtures.ts): FAILED 01–05/10
// on its first date, CANCELLED 10–12/10 before its first date, COMPLETED 14–15/10, CANCELLED
// 14–16/10 after committing 14 and 15/10, COMPLETED_WITH_ISSUES 14–16/10. A test that follows
// a run scripts what the API reports on each poll (`serveJobs`); the preview and every write
// answer what the test serves.

const PAGE = '/central-de-controle?tab=processamentos';

function problemResponse(status: number, code: string, message: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: 'Erro', status, errors: [{ code, message, field: null }] },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );
}

/** Serves `preview` as the API's answer to `GET /processing/preview`, whatever the range. */
function servePreview(preview: ProcessingPreview) {
  server.use(http.get(url('/processing/preview'), () => HttpResponse.json(preview)));
}

/** The preview of [start, end], whose day before is `before`, with each chain's state there. */
function previewOf(
  start: string,
  end: string,
  before: string,
  totalDays: number,
  cash: PredecessorState,
  positions: PredecessorState,
  scope: ProcessingScope = 'ALL',
): ProcessingPreview {
  return {
    start_date: start,
    end_date: end,
    total_days: totalDays,
    scope,
    predecessor_date: before,
    predecessor: { cash, positions },
  };
}

/**
 * Answers each enqueue with the queued run, which the job list includes from then on. Records
 * the bodies; `gate` holds each answer until it resolves.
 */
function answerEnqueue(jobs: { items: ProcessingRequest[] }, gate?: Promise<void>) {
  const bodies: unknown[] = [];
  server.use(
    http.post(url('/processing/requests'), async ({ request }) => {
      const body = (await request.json()) as Pick<
        ProcessingRequest,
        'start_date' | 'end_date' | 'scope'
      >;
      bodies.push(body);
      if (gate) await gate;
      const queued = job({
        ...body,
        id: `9a00000${bodies.length}-0000-4000-8000-000000000000`,
        created_at: `2026-10-18T11:0${bodies.length}:00-03:00`,
      });
      jobs.items = [queued, ...jobs.items];
      return HttpResponse.json(queued, { status: 201 });
    }),
  );
  return bodies;
}

/** Answers a cancel with `answer`, which the job list shows from then on. Counts the cancels. */
function answerCancel(jobs: { items: ProcessingRequest[] }, answer: ProcessingRequest) {
  const cancels = { count: 0 };
  server.use(
    http.post(url('/processing/requests/:id/cancel'), () => {
      cancels.count += 1;
      jobs.items = jobs.items.map((j) => (j.id === answer.id ? answer : j));
      return HttpResponse.json(answer);
    }),
  );
  return cancels;
}

/** Serves `run` as the newest job, above the fixtures' history. */
const serveWith = (...runs: ProcessingRequest[]) => serveJobs([...runs, ...processingRequests]);

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
    expect(
      await screen.findByText('A data 01/01/2099 não pode ser posterior a hoje e foi ignorada.'),
    ).toBeInTheDocument();
  });

  it('OQ-14 OQ-29 refuses a typed future end date on its field', async () => {
    const { user } = renderApp(`${PAGE}&inicio=2026-10-16&fim=2026-10-17`);

    const end = await screen.findByRole('textbox', { name: 'Data final' });
    await user.clear(end);
    await user.type(end, '19/10/2026');
    await user.tab();

    expect(await screen.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
    expect(end).toHaveAttribute('aria-invalid', 'true');
    expect(end).not.toHaveValue('17/10/2026');
    expect(screen.getByRole('button', { name: 'Solicitar processamento' })).toBeDisabled();
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
    servePreview(previewOf('2026-10-15', '2026-10-16', '2026-10-14', 2, 'PROCESSED', 'PROCESSED'));
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
    servePreview(
      previewOf('2026-10-17', '2026-10-18', '2026-10-16', 2, 'PROCESSED', 'PROCESSED_WITH_ISSUES'),
    );
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
    servePreview(
      previewOf('2026-10-18', '2026-10-18', '2026-10-17', 1, 'NOT_PROCESSED', 'NOT_PROCESSED'),
    );
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

  it('OQ-36 in Tudo, a day before missing for one chain only warns that this chain fails and the other goes on', async () => {
    // Cash has 17/10; positions do not.
    servePreview(
      previewOf('2026-10-18', '2026-10-18', '2026-10-17', 1, 'PROCESSED', 'NOT_PROCESSED'),
    );
    const { user } = renderApp(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
    const warnings = await modal.findAllByRole('alert');
    expect(warnings.map((w) => w.textContent)).toEqual([
      'O fechamento das posições de 17/10/2026 não foi processado. O fechamento das posições falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia; o fechamento do caixa seguirá até o fim do período. Processe antes um intervalo que inclua esse dia.',
    ]);
  });

  it.each([
    ['Caixa', 'CASH', 'Estado anterior do caixa', 0],
    ['Posições', 'POSITIONS', 'Estado anterior das posições', 1],
  ] as const)(
    'OQ-39 the preview returns both chains; %s shows and warns only for its own chain',
    async (scope, code, shown, warnings) => {
      // Cash has 17/10; positions do not. The API answers both chains for any scope.
      servePreview(
        previewOf('2026-10-18', '2026-10-18', '2026-10-17', 1, 'PROCESSED', 'NOT_PROCESSED', code),
      );
      const { user } = renderApp(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

      await user.click(await screen.findByRole('radio', { name: scope }));
      await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Confirmar processamento' }));
      await modal.findByRole('group', { name: shown });
      expect(modal.getAllByRole('group', { name: /Estado anterior/ })).toHaveLength(1);
      expect(modal.queryAllByRole('alert')).toHaveLength(warnings);
    },
  );

  it('OQ-21 the scope defaults to Tudo and Caixa warns only about the cash chain', async () => {
    servePreview(
      previewOf(
        '2026-10-17',
        '2026-10-18',
        '2026-10-16',
        2,
        'PROCESSED',
        'PROCESSED_WITH_ISSUES',
        'CASH',
      ),
    );
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
    servePreview(
      previewOf('2026-10-17', '2026-10-18', '2026-10-16', 2, 'PROCESSED', 'NOT_PROCESSED', 'CASH'),
    );
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
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
    servePreview(
      previewOf('2026-10-17', '2026-10-18', '2026-10-16', 2, 'PROCESSED', 'PROCESSED_WITH_ISSUES'),
    );
    answerEnqueue(serveJobs([...processingRequests]));
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
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
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
    expect(bodies).toEqual([]);
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
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
    const { user } = renderApp(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    const dialog = await openConfirmation(user);
    await user.dblClick(dialog.getByRole('button', { name: 'Confirmar processamento' }));

    await findJobRow('14/10/2026 a 16/10/2026', 'Na fila');
    expect(bodies).toHaveLength(1);
    expect(screen.getByText('6 processamentos encontrados')).toBeInTheDocument();
  });

  it('§10.2 keeps the confirmation open while the job is being queued, then allows another', async () => {
    let open: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      open = resolve;
    });
    const bodies = answerEnqueue(serveJobs([...processingRequests]), gate);
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
      expect(bodies).toHaveLength(2);
    });
    expect(await screen.findByText('7 processamentos encontrados')).toBeInTheDocument();
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
        const jobs = processingRequests;
        return params.get('cursor') === 'page-2'
          ? HttpResponse.json({ items: jobs.slice(2), next_cursor: null })
          : HttpResponse.json({ items: jobs.slice(0, 2), next_cursor: 'page-2' });
      }),
    );
    const { user } = renderApp(PAGE);

    expect(await screen.findByText('2 processamentos exibidos')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Carregar mais' }));

    expect(await screen.findByText('5 processamentos encontrados')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Carregar mais' })).not.toBeInTheDocument();
    // Older finished jobs from page 2 are history, not news: no "job finished" refresh rereads
    // the pages (review finding, PR for frontend/contract-review).
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(seen).toEqual(['limit=20', 'limit=20&cursor=page-2']);
  });

  it('P21 a search with no match among the loaded jobs points to "Carregar mais"', async () => {
    server.use(
      http.get(url('/processing/requests'), () =>
        HttpResponse.json({ items: processingRequests.slice(0, 2), next_cursor: 'page-2' }),
      ),
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

  it('OQ-20 OQ-46 offers only the actions each status allows; a cancel already asked shows Cancelando', async () => {
    serveWith(
      job(),
      // OQ-46: the API keeps a run RUNNING with its cancel request set; the screen says Cancelando.
      job({
        ...RUNNING,
        id: 'aa000000-0000-4000-8000-000000000002',
        start_date: '2026-10-15',
        created_at: '2026-10-18T09:00:00-03:00',
        cancel_requested_at: '2026-10-18T10:05:00-03:00',
      }),
    );
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
    serveJobs(processingRequests.map((j) => (j.status === 'FAILED' ? { ...j, scope: 'CASH' } : j)));
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
    const jobs = serveJobs([...processingRequests]);
    renderApp(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');
    const before = jobs.polls;

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(jobs.polls).toBe(before);
  });

  it('§12 polls every 2 s while a job is active, and stops once it has finished', async () => {
    const jobs = serveWith(job());
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    const before = jobs.polls;

    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(jobs.polls).toBe(before + 1);

    // QUEUED → RUNNING (17/10) → RUNNING (18/10) → COMPLETED_WITH_ISSUES; no dispatch (OQ-46).
    const started = { status: 'RUNNING', started_at: '2026-10-18T10:00:02-03:00' } as const;
    jobs.items = [job(started), ...processingRequests];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    const running = await findJobRow('17/10/2026 a 18/10/2026', 'Processando');
    expect(running.getByText('0 / 2 dias')).toBeInTheDocument();
    jobs.items = [job({ ...started, progress_date: '2026-10-17' }), ...processingRequests];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', '1 / 2 dias');
    const issuesBefore = issueReads.count;
    jobs.items = [
      job({
        ...started,
        status: 'COMPLETED_WITH_ISSUES',
        progress_date: '2026-10-18',
        finished_at: '2026-10-18T10:00:09-03:00',
      }),
      ...processingRequests,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', 'Concluído com pendências');

    // The finished job refreshes the published results and the pendências once.
    await waitFor(() => {
      expect(issueReads.count).toBe(issuesBefore + 1);
    });
    const afterFinish = jobs.polls;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(jobs.polls).toBe(afterFinish);
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
    const jobs = serveWith(job());
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    await waitFor(() => {
      expect(issueReads.count).toBeGreaterThan(0);
    });
    const before = issueReads.count;

    // Queued and finished elsewhere between two polls.
    jobs.items = [
      job({
        id: 'bb000000-0000-4000-8000-000000000001',
        start_date: '2026-10-15',
        end_date: '2026-10-15',
        status: 'COMPLETED',
        created_at: '2026-10-18T11:00:00-03:00',
        progress_date: '2026-10-15',
      }),
      ...jobs.items,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await findJobRow('15/10/2026 a 15/10/2026', 'Concluído');
    await waitFor(() => {
      expect(issueReads.count).toBe(before + 1);
    });
  });
});

describe('Processamentos: UTC timestamps (OQ-46, #93)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 compares creation times as instants: an older job in UTC is not news', async () => {
    const jobs = serveWith(job({ created_at: '2026-10-18T22:00:00-03:00' })); // 19/10 01:00 UTC
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    await waitFor(() => {
      expect(issueReads.count).toBeGreaterThan(0);
    });
    const before = issueReads.count;

    // Finished, but created before the newest job seen: its string sorts later, its instant not.
    // Newest first by instant, so it comes second.
    const [newest, ...older] = jobs.items;
    jobs.items = [
      newest as ProcessingRequest,
      job({
        id: 'bb000000-0000-4000-8000-000000000001',
        start_date: '2026-10-15',
        end_date: '2026-10-15',
        status: 'COMPLETED',
        created_at: '2026-10-19T00:59:00Z',
        progress_date: '2026-10-15',
      }),
      ...older,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await findJobRow('15/10/2026 a 15/10/2026', 'Concluído');
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(issueReads.count).toBe(before);
  });
});

describe('Processamentos: cancel (§10.2)', () => {
  it('§10.2 cancels a queued job at once, after confirmation', async () => {
    const jobs = serveWith(job());
    const cancels = answerCancel(
      jobs,
      job({
        status: 'CANCELLED',
        cancel_requested_at: '2026-10-18T10:05:00-03:00',
        finished_at: '2026-10-18T10:05:00-03:00',
      }),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));

    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    expect(dialog.getByText('aa000000')).toBeInTheDocument();
    expect(dialog.getByText('17/10/2026 a 18/10/2026')).toBeInTheDocument();
    expect(dialog.getByText('0 / 2 dias')).toBeInTheDocument();
    expect(dialog.getByText('Na fila')).toBeInTheDocument();
    // A queued run is cancelled at once (interfaces "Processing"): no date is in progress.
    expect(
      dialog.getByText(
        'O processamento ainda não começou e será cancelado imediatamente. Nenhuma data será processada.',
      ),
    ).toBeInTheDocument();
    expect(dialog.queryByText(/ao fim da data em andamento/)).toBeNull();
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Cancelar processamento?' })).toBeNull();
    });
    expect(cancels.count).toBe(1);
  });

  it('§10.2 goes back without cancelling', async () => {
    const jobs = serveWith(job());
    const cancels = answerCancel(jobs, job({ status: 'CANCELLED' }));
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Voltar' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Cancelar processamento?' })).toBeNull();
    });
    expect(cancels.count).toBe(0);
    expect(jobRow('17/10/2026 a 18/10/2026', 'Na fila')).toBeTruthy();
  });

  it('§10.2 OQ-23 OQ-46 cancels a running job cooperatively: Cancelando, then Cancelado', async () => {
    // On 17/10 of 17–18/10: the current date commits, 18/10 is not processed. (A cancel during
    // the last date would let the run complete, OQ-26 item 9.)
    const running = job({ ...RUNNING, progress_date: null });
    const jobs = serveWith(running);
    // The API keeps the run RUNNING with cancel_requested_at set (OQ-46).
    answerCancel(jobs, { ...running, cancel_requested_at: '2026-10-18T10:05:00-03:00' });
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    expect(
      dialog.getByText(
        'O processamento será interrompido ao fim da data em andamento. As datas já processadas continuam publicadas; as seguintes não serão processadas.',
      ),
    ).toBeInTheDocument();
    expect(dialog.queryByText(/cancelado imediatamente/)).toBeNull();
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    const row = await findJobRow('17/10/2026 a 18/10/2026', 'Cancelando');
    expect(row.queryByText('Processando')).not.toBeInTheDocument();
    // 17/10 commits; the run ends CANCELLED on the next poll.
    jobs.items = [
      job({
        ...RUNNING,
        status: 'CANCELLED',
        cancel_requested_at: '2026-10-18T10:05:00-03:00',
        finished_at: '2026-10-18T10:05:30-03:00',
      }),
      ...processingRequests,
    ];
    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado', 3_000);
  }, 10_000);

  it('OQ-46 shows the API message when a cancel was already asked', async () => {
    serveWith(job({ ...RUNNING, progress_date: null }));
    // Cancelled elsewhere in the meantime: the API refuses a second cancel.
    server.use(
      http.post(url('/processing/requests/:id/cancel'), () =>
        problemResponse(
          409,
          'JOB_NOT_CANCELLABLE',
          'O cancelamento deste processamento já foi solicitado.',
        ),
      ),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'O cancelamento deste processamento já foi solicitado.',
    );
  });

  it('OQ-15 shows the 409 message when the job can no longer be cancelled', async () => {
    serveWith(job());
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
  it('OQ-46 the details of a running job with a cancel asked show Cancelando and no cancel action', async () => {
    serveWith(job({ ...RUNNING, cancel_requested_at: '2026-10-18T13:05:00Z' }));
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Cancelando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Cancelando');
    expect(field(modal, 'Data em processamento').getByText('18/10/2026')).toBeInTheDocument();
    expect(modal.queryByRole('button', { name: 'Cancelar processamento' })).not.toBeInTheDocument();
  });

  it('§10.2 from the details, "Cancelar processamento" moves the focus into the cancel dialog', async () => {
    serveWith(job(RUNNING));
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

  it('§11.1 OQ-23 OQ-44 shows a failed run: times in Brasília, days, the date it failed on, its error', async () => {
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
    // A technical failure of no chain (OQ-44): its date, no chain, the API's message.
    expect(modal.getByRole('alert')).toHaveTextContent('Erro técnico ao processar a data.');
    expect(modal.queryByRole('group', { name: 'Cadeia com erro' })).not.toBeInTheDocument();
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

  /** A Tudo run where positions failed on 17/10 and cash went on to the end (OQ-36). */
  const PARTIAL = {
    status: 'COMPLETED_WITH_ISSUES',
    start_date: '2026-10-16',
    progress_date: '2026-10-18',
    error_code: 'POSITIONS_PREDECESSOR_MISSING',
    error_message: 'Dia anterior não processado',
    failed_date: '2026-10-17',
    failed_chain: 'POSITIONS',
    dispatched_at: '2026-10-18T10:00:01-03:00',
    started_at: '2026-10-18T10:00:02-03:00',
    finished_at: '2026-10-18T10:00:09-03:00',
  } as const;

  it('OQ-36 OQ-40 a Concluído com pendências Tudo run where a chain failed shows the error, its date and chain', async () => {
    serveWith(job(PARTIAL));
    const { user } = renderApp(PAGE);

    const menu = within(
      await openMenu(user, '16/10/2026 a 18/10/2026', 'Concluído com pendências'),
    );
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Solicitar novo processamento (Posições)',
    ]);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Dia anterior não processado');
    expect(field(modal, 'Data com erro').getByText('17/10/2026')).toBeInTheDocument();
    expect(field(modal, 'Cadeia com erro').getByText('Posições')).toBeInTheDocument();
    // What each chain published (OQ-36 item 1): positions stopped on 17/10, cash reached the end.
    expect(
      modal.getByText('Caixa: as datas de 16/10/2026 a 18/10/2026 foram publicadas.'),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 16/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
  });

  it('OQ-36 a Falhou Tudo run where the chains failed on different dates says what each published', async () => {
    serveWith(
      job({
        ...PARTIAL,
        status: 'FAILED',
        progress_date: '2026-10-17',
        error_code: 'PROCESSING_ERROR',
        error_message: 'Falha nas posições de 17/10/2026.',
      }),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '16/10/2026 a 18/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(
      modal.getByText(
        'Caixa: as datas de 16/10/2026 a 17/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 16/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByText(/^As datas de/)).not.toBeInTheDocument();
  });

  it('OQ-40 the failed-chain retry prefills that chain from failed_date to the original end', async () => {
    serveWith(job(PARTIAL));
    const { user, router } = renderApp(PAGE);

    const menu = within(
      await openMenu(user, '16/10/2026 a 18/10/2026', 'Concluído com pendências'),
    );
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    await user.click(
      modal.getByRole('button', { name: 'Solicitar novo processamento (Posições)' }),
    );

    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-17&fim=2026-10-18&escopo=posicoes',
    );
    expect(screen.getByRole('radio', { name: 'Posições' })).toBeChecked();
  });

  it('OQ-36 OQ-40 a Cancelado Tudo run after a chain failed keeps the error and offers both retries', async () => {
    serveWith(
      job({
        status: 'CANCELLED',
        start_date: '2026-10-15',
        progress_date: '2026-10-16',
        error_code: 'PROCESSING_ERROR',
        error_message: 'Falha ao processar o caixa de 16/10/2026.',
        failed_date: '2026-10-16',
        failed_chain: 'CASH',
        started_at: '2026-10-18T10:00:02-03:00',
        finished_at: '2026-10-18T10:00:09-03:00',
        cancel_requested_at: '2026-10-18T10:00:05-03:00',
      }),
    );
    const { user, router } = renderApp(PAGE);

    let menu = within(await openMenu(user, '15/10/2026 a 18/10/2026', 'Cancelado'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Solicitar novo processamento',
      'Solicitar novo processamento (Caixa)',
    ]);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Falha ao processar o caixa de 16/10/2026.');
    expect(field(modal, 'Cadeia com erro').getByText('Caixa')).toBeInTheDocument();
    // Cash read Erro on 16/10, so only positions published it (OQ-36 item 10).
    expect(
      modal.getByText(
        'Caixa: as datas de 15/10/2026 a 15/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 15/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByText(/^As datas de/)).not.toBeInTheDocument();
    await user.click(modal.getByRole('button', { name: 'Solicitar novo processamento' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-17&fim=2026-10-18&escopo=tudo',
    );

    menu = within(await openMenu(user, '15/10/2026 a 18/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Solicitar novo processamento (Caixa)' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-16&fim=2026-10-18&escopo=caixa',
    );
  });

  it('OQ-36 a Concluído com pendências run with only missing prices shows no error and no retry', async () => {
    const { user } = renderApp(PAGE);

    const menu = within(
      await openMenu(user, '14/10/2026 a 16/10/2026', 'Concluído com pendências'),
    );
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Ver detalhes']);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
    expect(modal.queryByRole('group', { name: 'Cadeia com erro' })).not.toBeInTheDocument();
    expect(modal.queryByRole('button', { name: /Solicitar novo/ })).not.toBeInTheDocument();
  });

  it('§11.1 still shows an error box for a failed job without a message', async () => {
    serveWith(
      job({
        status: 'FAILED',
        error_code: 'PROCESSING_ERROR',
        finished_at: '2026-10-18T10:01:00-03:00',
      }),
    );
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
    serveWith(job({ ...RUNNING, created_at: '2026-10-18T09:58:00-03:00' }));
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
