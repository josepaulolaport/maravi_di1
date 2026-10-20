import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { job, processingRequests } from '@/test/msw/fixtures';
import { url } from '@/test/helpers';
import { server, serveJobs } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

import {
  PAGE,
  serveWith,
  RUNNING,
  history,
  jobRow,
  findJobRow,
  closeMenu,
  openMenu,
} from '@/test/screens/processing';

describe('Processamentos: history (§11.1, §10.3)', () => {
  it('§10.3 lists every job with its period, progress and pt-BR status', async () => {
    renderRoute(PAGE);

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
    const { user } = renderRoute(PAGE);
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
    renderRoute(PAGE);

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
    const { user } = renderRoute(PAGE);

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
    const { user } = renderRoute(PAGE);
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
    const { user } = renderRoute(PAGE);

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
    const { user, router } = renderRoute(PAGE);

    // Cancelled after committing 14/10 and 15/10: what is left is 16/10.
    const menu = within(await openMenu(user, '14/10/2026 a 16/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Solicitar novo processamento' }));

    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-16&fim=2026-10-16&escopo=tudo',
    );
  });

  it('OQ-20 OQ-21 OQ-23 prefills a new request from the failed date, with the scope of the run', async () => {
    serveJobs(processingRequests.map((j) => (j.status === 'FAILED' ? { ...j, scope: 'CASH' } : j)));
    const { user, router } = renderRoute(PAGE);

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
