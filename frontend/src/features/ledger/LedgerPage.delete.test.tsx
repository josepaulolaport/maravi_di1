import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import { cashEntries, tradeEntries } from '@/test/msw/fixtures';
import { fieldError, problem, url } from '@/test/msw/handlers';
import { captureBodies, server } from '@/test/msw/server';

import {
  FULL_RANGE,
  openLedger,
  rowNamed,
  serveEntries,
  answerDeletes,
  serveSearch,
  DI1F28_ENTRIES,
} from './ledgerPage.support';

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('delete (§6.1)', () => {
    const sale = 'Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22';
    // Accessible names keep the no-break space Intl puts after "R$".
    const withdrawal = 'Retirada 16/10/2026 17:30 -R$\u00a050.000,00';

    it('§6.1 deletes one trade after confirmation, by its id; there is no edit action', async () => {
      answerDeletes(serveEntries());
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      expect(screen.queryByRole('menuitem', { name: /Editar/ })).not.toBeInTheDocument();
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      expect(dialog.getByText(sale, { exact: false })).toBeInTheDocument();
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('Lançamento excluído.')).toBeInTheDocument();
      expect(bodies).toEqual([{ ids: [tradeEntries[2]?.id] }]);
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${sale}` }),
      ).not.toBeInTheDocument();
    });

    it('§6.1 deletes one cash entry after confirmation', async () => {
      answerDeletes(serveEntries());
      const { user } = await openLedger();

      await user.click(
        rowNamed(withdrawal).getByRole('button', { name: `Ações de ${withdrawal}` }),
      );
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${withdrawal}` }),
      ).not.toBeInTheDocument();
    });

    it('OQ-51 names a cash entry with its description in the delete dialog', async () => {
      const deposit = 'Aporte 14/10/2026 09:00 +R$\u00a01.500.000,00 (Aporte inicial)';
      const { user } = await openLedger();

      await user.click(rowNamed(deposit).getByRole('button', { name: `Ações de ${deposit}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      // getByText normalizes the no-break space to a plain one.
      expect(
        dialog.getByText(deposit.replace('\u00a0', ' '), { exact: false }),
      ).toBeInTheDocument();
    });

    it('§6.1 a failed single delete keeps the entry and shows why', async () => {
      server.use(
        http.post(url('/ledger/entries/deletions'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]),
        ),
      );
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 a new range or search drops the selection', async () => {
      serveSearch({ DI1F28: DI1F28_ENTRIES });
      const { user, router } = await openLedger();
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      expect(screen.getByRole('button', { name: 'Excluir selecionados' })).toBeInTheDocument();

      await router.navigate('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
      await router.navigate(FULL_RANGE);
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();

      expect(screen.getByRole('checkbox', { name: `Selecionar ${sale}` })).not.toBeChecked();
      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      const box = screen.getByRole('textbox', { name: 'Buscar' });
      await user.type(box, 'DI1F28');
      expect(await screen.findByText('2 lançamentos encontrados')).toBeInTheDocument();
      await user.clear(box);
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();

      expect(screen.getByRole('checkbox', { name: `Selecionar ${sale}` })).not.toBeChecked();
    });

    it('§6.1 tells apart two same-day cash entries of the same amount by their time', async () => {
      const withdrawalEntry = cashEntries[1];
      const twin = { ...withdrawalEntry, id: 'twin', time: '18:05:00' };
      server.use(
        http.get(url('/ledger/entries'), () =>
          HttpResponse.json({ items: [twin, withdrawalEntry], next_cursor: null }),
        ),
      );
      await openLedger();

      expect(
        screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('checkbox', {
          name: 'Selecionar Retirada 16/10/2026 18:05 -R$\u00a050.000,00',
        }),
      ).toBeInTheDocument();
    });

    it('§6.1 "Voltar" leaves the entry in place', async () => {
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      await user.click(await screen.findByRole('button', { name: 'Voltar' }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 deletes the selected entries, of both types, in one atomic request', async () => {
      answerDeletes(serveEntries());
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      expect(dialog.getByText(/2 lançamentos selecionados/)).toBeInTheDocument();
      expect(dialog.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        withdrawal,
        sale,
      ]);
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('2 lançamentos excluídos.')).toBeInTheDocument();
      expect(bodies).toEqual([{ ids: [cashEntries[1]?.id, tradeEntries[2]?.id] }]);
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 "Selecionar todos" selects every listed entry', async () => {
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: 'Selecionar todos' }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      expect(dialog.getByText(/5 lançamentos selecionados/)).toBeInTheDocument();
    });

    it('§6.1 a failed multiple delete removes nothing and shows the error', async () => {
      server.use(
        http.post(url('/ledger/entries/deletions'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]),
        ),
      );
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    /**
     * Another tab or user deleted the sale after this screen listed it (QA 2026-10-19 #1): the
     * API answers the first deletion 404, deleting nothing (OQ-32), and lists the entries
     * without the sale from then on; a later deletion succeeds.
     */
    function saleDeletedElsewhere() {
      const ledger = serveEntries();
      let deletions = 0;
      server.use(
        http.post(url('/ledger/entries/deletions'), async ({ request }) => {
          deletions += 1;
          if (deletions === 1) {
            ledger.items = ledger.items.filter((e) => e.id !== tradeEntries[2]?.id);
            return problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]);
          }
          const { ids } = (await request.clone().json()) as { ids: string[] };
          ledger.items = ledger.items.filter((e) => !ids.includes(e.id));
          return new HttpResponse(null, { status: 204 });
        }),
      );
    }

    it('OQ-32 a 404 on a multiple delete refreshes the list and a retry deletes what is left', async () => {
      saleDeletedElsewhere();
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      // Nothing was deleted (all or nothing); the list now omits the vanished entry, and so do
      // the selection and the dialog.
      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      await waitFor(() => {
        expect(dialog.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
          withdrawal,
        ]);
      });
      expect(dialog.getByText(/1 lançamento selecionado/)).toBeInTheDocument();
      // The user is told which entry left the dialog, since the 404 does not name it.
      expect(
        screen.getByText(`Retirado da exclusão por já não existir: ${sale}.`),
      ).toBeInTheDocument();

      await user.click(dialog.getByRole('button', { name: 'Excluir' }));
      expect(await screen.findByText('Lançamento excluído.')).toBeInTheDocument();
      expect(bodies).toEqual([
        { ids: [cashEntries[1]?.id, tradeEntries[2]?.id] },
        { ids: [cashEntries[1]?.id] },
      ]);
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();
    });

    it('OQ-32 a 404 for an entry already deleted elsewhere closes the dialog and refreshes the list', async () => {
      saleDeletedElsewhere();
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = await screen.findByRole('dialog', { name: 'Excluir lançamento' });
      await user.click(within(dialog).getByRole('button', { name: 'Excluir' }));

      expect(
        await screen.findByText(
          'Lançamento não encontrado. Ele já havia sido excluído; a lista foi atualizada.',
        ),
      ).toBeInTheDocument();
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      await waitFor(() => {
        expect(screen.queryByRole('dialog', { name: 'Excluir lançamento' })).toBeNull();
      });
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${sale}` }),
      ).not.toBeInTheDocument();
    });
  });
});
