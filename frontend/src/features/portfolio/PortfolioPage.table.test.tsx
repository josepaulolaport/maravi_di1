import { screen, waitFor } from '@testing-library/react';
import { notifications } from '@mantine/notifications';

import { renderApp } from '@/test/render';

import {
  expectNoCard,
  rowOf,
  POSITIONS_15,
  override15,
  openCarteira,
} from './portfolioPage.support';

// The notifications store is module-global: a notice of one test must not stay for the next.
afterEach(() => {
  notifications.clean();
});

describe('Carteira (§11.4)', () => {
  it('§11.4 filters positions by asset code, with the search in the URL', async () => {
    const { user, router } = await openCarteira('2026-10-15');

    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'f29');

    await waitFor(() => {
      expect(screen.queryByText('DI1F28', { selector: 'td *' })).not.toBeInTheDocument();
    });
    expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    expect(router.state.location.search).toContain('busca=f29');
    await user.clear(screen.getByRole('textbox', { name: 'Buscar ativo' }));
    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'DI1F99');
    expect(await screen.findByText('Nenhum ativo encontrado.')).toBeInTheDocument();
  });

  it('§11.4 reads the positions search and order from the URL (a linked view)', async () => {
    renderApp('/carteira?date=2026-10-15&busca=f2&ordem=-financial_total');
    await screen.findByRole('group', { name: 'Saldo em caixa' });

    expect(screen.getByRole('textbox', { name: 'Buscar ativo' })).toHaveValue('f2');
    expect(screen.getByRole('columnheader', { name: 'Valor de mercado' })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(
      screen.getAllByText(/^DI1F\d\d$/, { selector: 'td *' }).map((el) => el.textContent),
    ).toEqual(['DI1F28', 'DI1F29']);
  });

  it('§11.4 sorts positions by market value, exactly from the decimal strings', async () => {
    const { user, router } = await openCarteira('2026-10-15');
    const assetOrder = () =>
      screen.getAllByText(/^DI1F\d\d$/, { selector: 'td *' }).map((el) => el.textContent);

    expect(assetOrder()).toEqual(['DI1F28', 'DI1F29']); // by maturity
    await user.click(screen.getByRole('button', { name: 'Valor de mercado' }));
    expect(assetOrder()).toEqual(['DI1F29', 'DI1F28']);
    expect(screen.getByRole('columnheader', { name: 'Valor de mercado' })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    await user.click(screen.getByRole('button', { name: 'Valor de mercado' }));
    expect(assetOrder()).toEqual(['DI1F28', 'DI1F29']);
    expect(router.state.location.search).toContain('ordem=-financial_total');
  });

  it('§8.3 P&L missing: no card, the asset is marked', async () => {
    const rows = POSITIONS_15.items;
    override15(
      {
        positions: {
          position_pnl: null,
          daily_pnl: null,
          cumulative_pnl: null,
          pnl_status: 'MISSING',
        },
      },
      {
        items: rows.map((row) =>
          row.asset_code === 'DI1F28'
            ? { ...row, position_pnl: null, daily_pnl: null, pnl_status: 'MISSING' as const }
            : row,
        ),
      },
    );
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(rowOf('DI1F28').getByText('P&L indisponível')).toBeInTheDocument();
    expect(rowOf('DI1F29').queryByText('P&L indisponível')).not.toBeInTheDocument();
  });

  it('§11.4 OQ-30/OQ-31 marks a row whose price was set after the processing (A10)', async () => {
    const { user } = await openCarteira('2026-10-16');

    const badge = rowOf('DI1F28').getByText('Preço alterado', { exact: false });
    expect(badge).toHaveTextContent('Preço alterado após o processamento — reprocesse');
    expect(rowOf('DI1F29').queryByText('Preço alterado', { exact: false })).not.toBeInTheDocument();
    await user.hover(badge);
    expect(
      await screen.findByRole('tooltip', {
        name: 'Preço alterado após o processamento — reprocesse',
      }),
    ).toBeInTheDocument();
  });

  it('§11.4 marks no row while every price predates the processing (A10)', async () => {
    await openCarteira('2026-10-15');

    expect(screen.queryByText('Preço alterado', { exact: false })).not.toBeInTheDocument();
  });

  it('§11.4 shows an empty table when no asset is expected on the date', async () => {
    override15({}, { items: [] });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Nenhuma posição nesta data.')).toBeInTheDocument();
  });
});
