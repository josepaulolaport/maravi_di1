import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { Issue } from '@/api/contract';
import { IDS } from '@/api/mocks/fixtures';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

// Expected values come from the fixture scenario (src/api/mocks/fixtures.ts): one
// MISSING_REFERENCE_PRICE issue for DI1F29 on 16/10/2026, and five finished jobs.

const PAGE = '/central-de-controle';

function serveIssues(items: Issue[]) {
  server.use(http.get(url('/processing/issues'), () => HttpResponse.json({ items })));
}

const issue = (changes: Partial<Issue>): Issue => ({
  id: '7d000000-0000-4000-8000-0000000000aa',
  issue_type: 'MISSING_REFERENCE_PRICE',
  asset_id: IDS.di1f29,
  asset_code: 'DI1F29',
  affected_date: '2026-10-16',
  required_price_date: '2026-10-16',
  request_id: '7f000000-0000-4000-8000-000000000002',
  ...changes,
});

function issueRow(text: string) {
  const row = screen.getByText(text, { selector: 'td, td *' }).closest('tr');
  if (!row) throw new Error(`no row for ${text}`);
  return within(row);
}

describe('Central de Controle (§11.1)', () => {
  it('§11.1 opens on Pendências, with the issue count on its tab', async () => {
    renderApp(PAGE);

    const tab = await screen.findByRole('tab', { name: /Pendências/ });
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(await within(tab).findByText('1')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Processamentos' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('§11.1 opens the tab named in ?tab= (deep link)', async () => {
    renderApp(`${PAGE}?tab=processamentos`);

    expect(await screen.findByRole('tab', { name: 'Processamentos' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(
      await screen.findByRole('heading', { name: 'Solicitar processamento' }),
    ).toBeInTheDocument();
  });

  it('§11.1 writes the chosen tab to ?tab=', async () => {
    const { user, router } = renderApp(PAGE);

    await user.click(await screen.findByRole('tab', { name: 'Processamentos' }));

    expect(router.state.location.search).toBe('?tab=processamentos');
    await user.click(screen.getByRole('tab', { name: /Pendências/ }));
    expect(router.state.location.search).toBe('?tab=pendencias');
  });

  it('§11.1 shows no financial KPIs', async () => {
    renderApp(PAGE);
    await screen.findByText('Preço de referência ausente');

    expect(screen.queryByText(/Saldo em caixa|Patrimônio|P&L/)).not.toBeInTheDocument();
  });
});

describe('Pendências (§11.1, §10.3)', () => {
  it('§10.3 lists the missing reference price with its date, asset and "Definir preço"', async () => {
    renderApp(PAGE);

    await screen.findByText('Preço de referência ausente');
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers.slice(0, 3)).toEqual(['Data', 'Ativo', 'Pendência']);
    const row = issueRow('DI1F29');
    expect(row.getByText('16/10/2026')).toBeInTheDocument();
    expect(row.getByText('Preço de referência ausente')).toBeInTheDocument();
    expect(row.getByRole('link', { name: 'Definir preço' })).toHaveAttribute(
      'href',
      `/ativos/contratos/${IDS.di1f29}?registrar=2026-10-16`,
    );
    expect(screen.getByText('1 pendência encontrada')).toBeInTheDocument();
  });

  it('§7.4 links an expired contract with an open position to its Lançamentos', async () => {
    serveIssues([
      issue({
        issue_type: 'EXPIRED_OPEN_POSITION',
        asset_id: IDS.di1f27,
        asset_code: 'DI1F27',
        affected_date: '2027-01-05',
        required_price_date: null,
      }),
    ]);
    renderApp(PAGE);

    const row = await screen.findByText('Contrato vencido com posição aberta');
    const cells = within(row.closest('tr') as HTMLElement);
    expect(cells.getByText('05/01/2027')).toBeInTheDocument();
    expect(cells.getByRole('link', { name: 'Ver lançamentos' })).toHaveAttribute(
      'href',
      '/lancamentos?busca=DI1F27',
    );
  });

  it('OQ-11 links a stale predecessor to Processamentos ending the day before', async () => {
    serveIssues([
      issue({
        issue_type: 'STALE_PREDECESSOR',
        asset_id: null,
        asset_code: null,
        affected_date: '2026-10-17',
        required_price_date: null,
      }),
    ]);
    const { user, router } = renderApp(PAGE);

    const text = await screen.findByText('Estado anterior desatualizado');
    const cells = within(text.closest('tr') as HTMLElement);
    expect(cells.getByText('—')).toBeInTheDocument();
    const link = cells.getByRole('link', { name: 'Processar intervalo anterior' });
    expect(link).toHaveAttribute('href', '/central-de-controle?tab=processamentos&fim=2026-10-16');

    await user.click(link);

    expect(router.state.location.search).toBe('?tab=processamentos&fim=2026-10-16');
    expect(await screen.findByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
  });

  it('§10.3 shows the date whose price is needed, which may differ from the affected day', async () => {
    serveIssues([issue({ affected_date: '2026-10-16', required_price_date: '2026-10-15' })]);
    const { user } = renderApp(PAGE);

    await screen.findByText('DI1F29');
    const row = issueRow('DI1F29');
    expect(row.getByText('15/10/2026')).toBeInTheDocument();
    expect(row.queryByText('16/10/2026')).not.toBeInTheDocument();
    expect(row.getByRole('link', { name: 'Definir preço' })).toHaveAttribute(
      'href',
      `/ativos/contratos/${IDS.di1f29}?registrar=2026-10-15`,
    );

    await user.type(screen.getByRole('textbox', { name: 'Buscar pendência' }), '15/10');
    expect(screen.getByText('DI1F29')).toBeInTheDocument();
  });

  it('§10.3 filters by asset or date', async () => {
    serveIssues([
      issue({}),
      issue({
        id: '7d000000-0000-4000-8000-0000000000bb',
        asset_id: IDS.di1f28,
        asset_code: 'DI1F28',
        affected_date: '2026-10-15',
        required_price_date: '2026-10-15',
      }),
    ]);
    const { user } = renderApp(PAGE);
    await screen.findByText('DI1F28');
    expect(screen.getByText('2 pendências encontradas')).toBeInTheDocument();

    const search = screen.getByRole('textbox', { name: 'Buscar pendência' });
    expect(search).toHaveAttribute('placeholder', 'Buscar ativo ou data...');
    await user.type(search, 'f28');
    expect(screen.queryByText('DI1F29')).not.toBeInTheDocument();
    expect(screen.getByText('DI1F28')).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, '16/10');
    expect(screen.getByText('DI1F29')).toBeInTheDocument();
    expect(screen.queryByText('DI1F28')).not.toBeInTheDocument();
    expect(screen.getByText('1 pendência encontrada')).toBeInTheDocument();
  });

  it('§11.1 says when there is nothing to show', async () => {
    serveIssues([]);
    renderApp(PAGE);

    expect(await screen.findByText('Nenhuma pendência encontrada.')).toBeInTheDocument();
    expect(screen.getByText('0 pendências encontradas')).toBeInTheDocument();
  });

  it('OQ-15 shows the API message when the list fails, with a retry', async () => {
    server.use(
      http.get(url('/processing/issues'), () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Erro',
            status: 500,
            errors: [{ code: 'VALIDATION_ERROR', message: 'Serviço indisponível.', field: null }],
          },
          { status: 500, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    renderApp(PAGE);

    expect(await screen.findByText('Serviço indisponível.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
  });
});
