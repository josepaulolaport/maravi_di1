import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { LedgerEntry } from '@/api/contract';
import { cashEntries, ledgerEntries, tradeEntries } from '@/test/msw/fixtures';
import { fieldError, problem, url, cellTexts } from '@/test/helpers';
import { server } from '@/test/msw/server';
import { addDays, formatDate, todayInSaoPaulo } from '@/shared/format';
import { renderRoute } from '@/test/render';

import {
  FULL_RANGE,
  openLedger,
  table,
  bodyRows,
  serveSearch,
  DI1F28_ENTRIES,
} from '@/test/screens/ledger';

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('list', () => {
    it('§11.3 shows a loading state, then the entries', async () => {
      renderRoute(FULL_RANGE);

      expect(await screen.findByLabelText('Carregando lançamentos')).toBeInTheDocument();
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 has separate columns for instrument type and entry type', async () => {
      await openLedger();

      const headers = within(table())
        .getAllByRole('columnheader')
        .map((h) => h.textContent);
      expect(headers).toEqual([
        '',
        'Data e hora',
        'Tipo de ativo',
        'Tipo',
        'Ativo',
        'Qtd.',
        'PU',
        'Taxa',
        'Financeiro',
        'Ações',
      ]);
    });

    it('§11.3 explains the Financeiro column as the cash effect in a keyboard-reachable tooltip', async () => {
      const { user } = await openLedger();

      const trigger = within(table()).getByText('Financeiro');
      await user.tab();
      while (document.activeElement !== trigger && document.activeElement !== document.body) {
        await user.tab();
      }
      expect(trigger).toHaveFocus();
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        'Efeito no caixa: compra negativa, venda positiva; aporte positivo, retirada negativa.',
      );
    });

    it('§11.3 lists trades and cash entries in one order, newest first, in pt-BR formats', async () => {
      await openLedger();
      await screen.findAllByText('Futuros');

      expect(bodyRows().map(cellTexts)).toEqual([
        ['', '16/10/2026 17:30', 'Caixa', 'Retirada', '—', '—', '—', '—', '-R$ 50.000,00', ''],
        [
          '',
          '16/10/2026 15:00',
          'Futuros',
          'Venda',
          'DI1F28',
          '-4',
          '89.102,22',
          '9,9500%',
          '+R$ 356.408,89',
          '',
        ],
        [
          '',
          '15/10/2026 10:30',
          'Futuros',
          'Compra',
          'DI1F29',
          '+5',
          '82.057,00',
          '9,3203%',
          '-R$ 410.285,00',
          '',
        ],
        [
          '',
          '14/10/2026 14:10',
          'Futuros',
          'Compra',
          'DI1F28',
          '+10',
          '89.006,46',
          '10,0000%',
          '-R$ 890.064,63',
          '',
        ],
        ['', '14/10/2026 09:00', 'Caixa', 'Aporte', '—', '—', '—', '—', '+R$ 1.500.000,00', ''],
      ]);
    });

    it('§11.3 sorts by Data e hora, descending by default, ascending on click', async () => {
      const orders: (string | null)[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          const order = new URL(request.url).searchParams.get('order');
          orders.push(order);
          // The API's ascending answer: the same entries, oldest first.
          const items = order === 'asc' ? [...ledgerEntries].reverse() : ledgerEntries;
          return HttpResponse.json({ items, next_cursor: null });
        }),
      );
      const { user, router } = await openLedger();
      const header = screen.getByRole('columnheader', { name: 'Data e hora' });
      expect(header).toHaveAttribute('aria-sort', 'descending');

      await user.click(within(header).getByRole('button'));

      expect(header).toHaveAttribute('aria-sort', 'ascending');
      // The order is in the URL, so the view can be linked (`?ordem=asc`).
      expect(router.state.location.search).toContain('ordem=asc');
      // The order is the backend's: the screen asks for it, it never sorts the rows itself.
      await waitFor(() => {
        expect(orders).toEqual(['desc', 'asc']);
      });
      await waitFor(() => {
        expect(cellTexts(bodyRows()[0] as HTMLElement)[1]).toBe('14/10/2026 09:00');
      });
      expect(cellTexts(bodyRows()[4] as HTMLElement)[1]).toBe('16/10/2026 17:30');
    });

    it('§11.3 a new range shows the loading state, never the rows of the previous range', async () => {
      let release: () => void = () => undefined;
      const { router } = await openLedger();
      server.use(
        http.get(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );

      await router.navigate('/lancamentos?inicio=2026-10-01&fim=2026-10-05');

      expect(await screen.findByLabelText('Carregando lançamentos')).toBeInTheDocument();
      expect(screen.queryByText('5 lançamentos encontrados')).not.toBeInTheDocument();
      release();
    });

    it('§11.3 the range is inclusive on both ends', async () => {
      await openLedger('/lancamentos?inicio=2026-10-15&fim=2026-10-16');

      expect(screen.getByText('3 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[1])).toEqual([
        '16/10/2026 17:30',
        '16/10/2026 15:00',
        '15/10/2026 10:30',
      ]);
    });

    it('§11.3 a one-day range keeps the entries of that day', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-14');

      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 searches by asset from the URL (busca)', async () => {
      const searches = serveSearch({ DI1F28: DI1F28_ENTRIES });
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-16&busca=DI1F28');

      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('DI1F28');
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[4])).toEqual(['DI1F28', 'DI1F28']);
      expect(searches).toEqual(['DI1F28']);
    });

    it('§11.3 typing a search filters the list and keeps it in the URL', async () => {
      const searches = serveSearch({ retirada: [cashEntries[1] as LedgerEntry] });
      const { user, router } = await openLedger();

      await user.type(screen.getByRole('textbox', { name: 'Buscar' }), 'retirada');

      expect(await screen.findByText('1 lançamento encontrado')).toBeInTheDocument();
      expect(router.state.location.search).toContain('busca=retirada');
      expect(cellTexts(bodyRows()[0] as HTMLElement)[3]).toBe('Retirada');
      expect(searches.at(-1)).toBe('retirada');
    });

    it('§11.3 without inicio/fim, lists the 30 days ending today (São Paulo)', async () => {
      const today = todayInSaoPaulo();
      const start = addDays(today, -29);
      const seen: string[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          seen.push(new URL(request.url).search);
          return HttpResponse.json({ items: [], next_cursor: null });
        }),
      );

      await openLedger('/lancamentos?busca=DI1F29');

      expect(seen[0]).toBe(
        `?start_date=${start}&end_date=${today}&search=DI1F29&order=desc&limit=50`,
      );
      expect(screen.getByRole('button', { name: 'Período' })).toHaveTextContent(
        `${formatDate(start)} – ${formatDate(today)}`,
      );
    });

    it('P21 reads the list page by page: "Carregar mais" asks for the next cursor', async () => {
      const seen: (string | null)[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          const cursor = new URL(request.url).searchParams.get('cursor');
          seen.push(cursor);
          return cursor === 'page-2'
            ? HttpResponse.json({ items: tradeEntries.slice(0, 2), next_cursor: null })
            : HttpResponse.json({ items: cashEntries, next_cursor: 'page-2' });
        }),
      );
      const { user } = renderRoute(FULL_RANGE);

      expect(await screen.findByText('2 lançamentos exibidos')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Carregar mais' }));

      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Carregar mais' })).not.toBeInTheDocument();
      expect(seen.slice(0, 2)).toEqual([null, 'page-2']);
    });

    it('§11.3 shows the empty state for a range without entries', async () => {
      await openLedger('/lancamentos?inicio=2026-10-01&fim=2026-10-05');

      expect(screen.getByText('0 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByText('Nenhum lançamento no período.')).toBeInTheDocument();
    });

    it('§12 shows the API error with a retry', async () => {
      server.use(
        http.get(url('/ledger/entries'), () =>
          problem(422, [fieldError('INVALID_RANGE', 'Período inválido para a consulta.', null)]),
        ),
      );
      const { user } = renderRoute(FULL_RANGE);

      expect(await screen.findByText('Período inválido para a consulta.')).toBeInTheDocument();
      server.resetHandlers();
      await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 never shows an instrument type code: unavailable until the API names it', async () => {
      server.use(
        http.get(url('/instrument-types'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Tipos não encontrados.')]),
        ),
      );
      await openLedger();

      expect(screen.queryByText('FUTURE')).not.toBeInTheDocument();
      // Row 1 is the 16/10 venda (row 0 is the 17:30 retirada, whose type is always Caixa).
      expect(cellTexts(bodyRows()[1] as HTMLElement)[2]).toBe('—');
    });

    it('§11.3 clearing busca in the URL clears the search box and keeps it cleared', async () => {
      serveSearch({ DI1F28: DI1F28_ENTRIES });
      const { router } = await openLedger(`${FULL_RANGE}&busca=DI1F28`);
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();

      await router.navigate(FULL_RANGE);

      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('');
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(router.state.location.search).not.toContain('busca');
    });
  });
});
