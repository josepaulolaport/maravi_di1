import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { IDS } from '@/api/mocks/fixtures';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

// Expected values come from the fixture scenario (src/api/mocks/fixtures.ts). Each contract's
// latest observation: DI1F27 none; DI1F28 16/10 MANUAL revision 2 (PU 89250.3147019396, rate
// 0.0980, preferred over B3); DI1F29 15/10 MANUAL (PU 80206.1333187932, rate 0.1045); DI1F30
// none.

async function openProduct() {
  const result = renderApp(`/ativos/produtos/${IDS.di1}`);
  await screen.findByRole('heading', { name: 'DI1' });
  await screen.findByRole('table', { name: 'Contratos' });
  return result;
}

function contractRow(code: string) {
  const row = screen.getByText(code, { selector: 'td *' }).closest('tr');
  if (!row) throw new Error(`no row for ${code}`);
  return within(row);
}

function cellTexts(code: string) {
  return contractRow(code)
    .getAllByRole('cell')
    .map((cell) => cell.textContent);
}

describe('Ativos: produto (§11.2)', () => {
  it('§11.2 shows the breadcrumb, the title with its class and the product name', async () => {
    await openProduct();

    const breadcrumb = within(screen.getByRole('navigation', { name: 'Trilha' }));
    expect(breadcrumb.getByRole('link', { name: 'Ativos' })).toHaveAttribute('href', '/ativos');
    expect(breadcrumb.getByText('DI1')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Futuros de Taxa de Juros')).toBeInTheDocument();
    expect(
      screen.getByText('Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia'),
    ).toBeInTheDocument();
  });

  it('§11.2 shows no specification card (user, 2026-10-18)', async () => {
    await openProduct();

    expect(screen.queryByRole('region', { name: 'Especificações' })).not.toBeInTheDocument();
    expect(screen.queryByText('Valor de referência')).not.toBeInTheDocument();
    expect(screen.queryByText('Contagem de dias')).not.toBeInTheDocument();
    expect(screen.queryByText('Precificação')).not.toBeInTheDocument();
  });

  it('§11.2 §5 lists each contract with its latest observation next to its own date', async () => {
    await openProduct();

    const headers = within(screen.getByRole('table', { name: 'Contratos' }))
      .getAllByRole('columnheader')
      .map((th) => th.textContent);
    expect(headers).toEqual(['Contrato', 'Vencimento', 'Último PU', 'Taxa a.a.', 'Data ref.', '']);
    expect(cellTexts('DI1F28').slice(0, 5)).toEqual([
      'DI1F28',
      '03/01/2028',
      '89.250,31',
      '9,80%',
      '16/10/2026',
    ]);
    expect(cellTexts('DI1F29').slice(0, 5)).toEqual([
      'DI1F29',
      '02/01/2029',
      '80.206,13',
      '10,45%',
      '15/10/2026',
    ]);
    expect(screen.getByText('4 contratos cadastrados')).toBeInTheDocument();
  });

  it('§5 shows a contract without any observation as unavailable, never as zero', async () => {
    await openProduct();

    expect(cellTexts('DI1F27').slice(0, 5)).toEqual(['DI1F27', '04/01/2027', '—', '—', '—']);
  });

  it('§11.2 searches contracts by code and links each to its page', async () => {
    const { user, router } = await openProduct();

    const search = screen.getByRole('textbox', { name: 'Buscar contratos' });
    expect(search).toHaveAttribute('placeholder', 'Buscar contrato por código...');
    await user.type(search, 'f29');
    await waitFor(() => {
      expect(screen.queryByText('DI1F28', { selector: 'td *' })).not.toBeInTheDocument();
    });
    expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    expect(router.state.location.search).toContain('busca=f29');

    await user.click(screen.getByRole('link', { name: 'Abrir contrato DI1F29' }));
    expect(router.state.location.pathname).toBe(`/ativos/contratos/${IDS.di1f29}`);
  });

  it('§3 creates a contract and shows the API field errors on their fields', async () => {
    const { user } = await openProduct();

    await user.click(screen.getByRole('button', { name: 'Novo contrato' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Novo contrato' }));
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));
    expect(await modal.findByText('Informe o código do contrato.')).toBeInTheDocument();
    expect(modal.getByText('Informe o vencimento.')).toBeInTheDocument();

    await user.type(modal.getByRole('textbox', { name: 'Código' }), 'DI1F28');
    await user.type(modal.getByRole('textbox', { name: 'Vencimento' }), '02/01/2031');
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));
    expect(await modal.findByText('Já existe um contrato com este código.')).toBeInTheDocument();

    await user.clear(modal.getByRole('textbox', { name: 'Código' }));
    await user.type(modal.getByRole('textbox', { name: 'Código' }), 'DI1F31');
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));

    expect(await screen.findByText('DI1F31', { selector: 'td *' })).toBeInTheDocument();
    expect(cellTexts('DI1F31').slice(0, 5)).toEqual(['DI1F31', '02/01/2031', '—', '—', '—']);
    expect(await screen.findByText('5 contratos cadastrados')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Novo contrato' })).not.toBeInTheDocument();
    });
  });

  it('§12 shows "não encontrado" for an unknown product', async () => {
    renderApp('/ativos/produtos/desconhecido');

    expect(await screen.findByText('Produto não encontrado.')).toBeInTheDocument();
  });

  it('§11.2 says so when the product has no contract', async () => {
    server.use(http.get(url('/instruments'), () => HttpResponse.json({ items: [] })));
    renderApp(`/ativos/produtos/${IDS.di1}`);

    expect(await screen.findByText('Nenhum contrato encontrado.')).toBeInTheDocument();
  });
});
