import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import { preview } from '@/test/msw/fixtures';
import { fieldError, problem, url, type User } from '@/test/helpers';
import { captureBodies, server } from '@/test/msw/server';

import { openLedger, failCash } from '@/test/screens/ledger';

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('Processar (OQ-21, user 2026-10-18)', () => {
    async function openProcessar(user: User) {
      await user.click(screen.getByRole('button', { name: 'Processar' }));
      return within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
    }

    it('§10.1 prefills the whole period with Tudo (P19 dropped)', async () => {
      const { user } = await openLedger();

      const modal = await openProcessar(user);

      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('14/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Tudo' })).toBeChecked();
    });

    it('§11.3 "Processar caixa" starts at Caixa D0 when only D0 is behind', async () => {
      failCash('2026-10-16');
      const { user } = await openLedger();

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Caixa' })).toBeChecked();
    });

    it('§11.3 "Processar caixa" is offered when Caixa D0 was never processed', async () => {
      const { user } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-17');

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('17/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('17/10/2026');
    });

    it('§10.1 previews and queues the job without leaving Lançamentos', async () => {
      server.use(
        http.get(url('/processing/preview'), () =>
          HttpResponse.json({ ...preview, end_date: '2026-10-15', total_days: 2, scope: 'CASH' }),
        ),
      );
      const bodies = captureBodies('/processing/requests');
      const { user, router } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
      const modal = await openProcessar(user);
      await user.click(modal.getByRole('radio', { name: 'Caixa' }));

      expect(
        await modal.findByRole('group', { name: 'Estado anterior do caixa' }),
      ).toHaveTextContent('Estado inicial (sem lançamentos anteriores)');
      expect(modal.queryByRole('group', { name: 'Estado anterior das posições' })).toBeNull();
      await user.click(modal.getByRole('button', { name: 'Confirmar processamento' }));

      expect(
        await screen.findByText(
          'Processamento colocado na fila. Acompanhe em Central de Controle.',
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([{ start_date: '2026-10-14', end_date: '2026-10-15', scope: 'CASH' }]);
      expect(router.state.location.pathname).toBe('/lancamentos');
    });
  });

  describe('Processar: API errors (OQ-15)', () => {
    it('OQ-15 shows an error on scope under the Escopo group', async () => {
      server.use(
        http.post(url('/processing/requests'), () =>
          problem(422, [fieldError('VALIDATION_ERROR', 'Escopo não aceito.', 'scope')]),
        ),
      );
      const { user } = await openLedger();
      await user.click(screen.getByRole('button', { name: 'Processar' }));
      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      await modal.findByRole('group', { name: 'Estado anterior do caixa' });

      await user.click(modal.getByRole('button', { name: 'Confirmar processamento' }));

      const scope = await modal.findByRole('radiogroup', { name: 'Escopo' });
      await waitFor(() => {
        expect(scope).toHaveAccessibleDescription('Escopo não aceito.');
      });
    });
  });
});
