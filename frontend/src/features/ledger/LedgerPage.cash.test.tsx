import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http } from 'msw';

import { fieldError, problem, url } from '@/test/helpers';
import { server } from '@/test/msw/server';

import { openLedger, failCash, openNew, typeDate } from '@/test/screens/ledger';

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('future dates in the link (OQ-14)', () => {
    it('OQ-14 says a future end date in the link was ignored', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2099-01-01');

      expect(
        await screen.findByText('A data 01/01/2099 não pode ser posterior a hoje e foi ignorada.'),
      ).toBeInTheDocument();
    });
  });

  describe('cash strip (OQ-19 item 3)', () => {
    it('§11.3 OQ-21 shows the published cash of the range end and the day before, with its processing time', async () => {
      await openLedger();

      const before = within(screen.getByRole('group', { name: 'Caixa D−1' }));
      const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
      expect(before.getByText('15/10/2026')).toBeInTheDocument();
      expect(await before.findByText('R$ 199.650,37')).toBeInTheDocument();
      expect(end.getByText('16/10/2026')).toBeInTheDocument();
      expect(await end.findByText('R$ 506.059,27')).toBeInTheDocument();
      // A processed date carries no badge, only its processing time (OQ-31).
      for (const group of [before, end]) {
        expect(group.getByText('Processado em 16/10/2026 18:40')).toBeInTheDocument();
        expect(group.queryByText(/^(Processado|Erro|Não processado)$/)).not.toBeInTheDocument();
      }
      expect(screen.queryByRole('button', { name: 'Processar caixa' })).not.toBeInTheDocument();
    });

    it('OQ-23 "Processar caixa" from a failed Caixa D−1 covers D−1 to D0, scope Caixa', async () => {
      failCash('2026-10-15');
      const { user } = await openLedger();

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('15/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Caixa' })).toBeChecked();
    });

    it('OQ-23 a failed cash date keeps its published cash, reads "Erro" and offers "Processar caixa"', async () => {
      failCash('2026-10-16');
      await openLedger();

      const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
      expect(await end.findByText('R$ 506.059,27')).toBeInTheDocument();
      expect(end.getByText('Erro')).toBeInTheDocument();
      expect(await screen.findByRole('button', { name: 'Processar caixa' })).toBeInTheDocument();
    });

    it('§11.3 shows unprocessed dates as unavailable, never as zero', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-18');

      for (const [label, date] of [
        ['Caixa D−1', '17/10/2026'],
        ['Caixa D0', '18/10/2026'],
      ] as const) {
        const group = within(screen.getByRole('group', { name: label }));
        expect(group.getByText(date)).toBeInTheDocument();
        expect(await group.findByText('Não processado')).toBeInTheDocument();
        expect(group.getByText('—')).toBeInTheDocument();
      }
    });
  });

  it('§11.3 marks a load failure of the strip as unavailable', async () => {
    server.use(
      http.get(url('/portfolio/summary'), () =>
        problem(422, [fieldError('VALIDATION_ERROR', 'Data inválida.', 'date')]),
      ),
    );
    await openLedger();

    const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
    expect(await end.findByText('Erro ao carregar')).toBeInTheDocument();
    expect(end.getByText('—')).toBeInTheDocument();
  });

  it('OQ-31 a write keeps the strip as processed: the figure stays until reprocessed', async () => {
    const { user } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
    const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
    expect(await end.findByText('R$ 199.650,37')).toBeInTheDocument();

    const modal = await openNew(user, 'Aporte');
    await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
    await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
    await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

    await waitFor(() => {
      expect(modal.queryByRole('button', { name: 'Registrar aporte' })).not.toBeInTheDocument();
    });
    expect(end.getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(end.queryByText(/^(Erro|Não processado)$/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Processar caixa' })).not.toBeInTheDocument();
  });
});
