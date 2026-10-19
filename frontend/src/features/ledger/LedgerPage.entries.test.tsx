import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { LedgerEntry } from '@/api/contract';
import { IDS, instruments, products, tradeEntries } from '@/test/msw/fixtures';
import { fieldError, problem, url } from '@/test/msw/handlers';
import { captureBodies, server } from '@/test/msw/server';
import { formatDate, todayInSaoPaulo } from '@/shared/format';

import {
  openLedger,
  serveEntries,
  answerCreate,
  openNew,
  typeDate,
  chooseContract,
} from './ledgerPage.support';

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('Compra / Venda (§6.1)', () => {
    it('§6.1 registers a compra typed as PU, positive quantity', async () => {
      // The API's answer: the complementary rate and the cash amount are the backend's (DC/365).
      answerCreate(serveEntries(), {
        ...(tradeEntries[1] as LedgerEntry & { type: 'TRADE' }),
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-16',
        time: '16:45:00',
        seq: 6,
        signed_quantity: 3,
        execution_pu: '80000.00',
        execution_rate: '0.105918966419',
        input_kind: 'PU',
        cash_amount: '-240000.00',
        created_at: '2026-10-18T12:00:00-03:00',
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '16:45' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '3');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(
        await screen.findByText(
          /^Compra registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          type: 'TRADE',
          asset_id: IDS.di1f29,
          date: '2026-10-16',
          time: '16:45:00',
          signed_quantity: 3,
          input_kind: 'PU',
          execution_pu: '80000.00',
        },
      ]);
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(await screen.findByText('6 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 registers a venda typed as a rate, sent as a fraction with a negative quantity', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Venda');

      await chooseContract(user, modal, 'DI1F28');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '17:05' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '2');
      await user.click(modal.getByRole('radio', { name: 'Taxa a.a.' }));
      await user.type(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,45');
      await user.click(modal.getByRole('button', { name: 'Registrar venda' }));

      expect(
        await screen.findByText(
          /^Venda registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          type: 'TRADE',
          asset_id: IDS.di1f28,
          date: '2026-10-16',
          time: '17:05:00',
          signed_quantity: -2,
          input_kind: 'RATE',
          execution_rate: '0.1045',
        },
      ]);
    });

    it('OQ-13 suggests today and the current time, and has no PU/rate preview', async () => {
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveValue(
        formatDate(todayInSaoPaulo()),
      );
      expect(modal.getByLabelText<HTMLInputElement>('Hora', { exact: false }).value).toMatch(
        /^\d{2}:\d{2}$/,
      );
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.006,46');
      expect(modal.queryByRole('textbox', { name: 'Taxa a.a. (%)' })).not.toBeInTheDocument();
      expect(modal.queryByText(/%$/)).not.toBeInTheDocument();
    });

    it('OQ-15 keeps the modal open while saving, so the result is never lost', async () => {
      let release: () => void = () => undefined;
      server.use(
        http.post(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      await user.keyboard('{Escape}');
      // Past the modal's close transition: a closing modal would be gone by now.
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(modal.queryByRole('button', { name: 'Fechar' })).not.toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar compra' })).toBeInTheDocument();
      release();
      expect(
        await screen.findByText(
          /^Compra registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
    });

    it('§6.1 checks the required fields before sending', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(modal.getByText('Selecione um contrato.')).toBeInTheDocument();
      expect(modal.getByText('Informe uma quantidade inteira maior que zero.')).toBeInTheDocument();
      expect(modal.getByText('Informe o PU.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });

    it('OQ-3 shows the decimal-place error of a PU on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 10 casas decimais.', 'execution_pu'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,12345678901');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText('Use no máximo 10 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'PU' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('OQ-3 shows the decimal-place error of a rate on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 12 casas decimais.', 'execution_rate'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.click(modal.getByRole('radio', { name: 'Taxa a.a.' }));
      // 10,12345678901% = 0.1012345678901: 13 places, one more than OQ-3 allows.
      await user.type(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,12345678901');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText('Use no máximo 12 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it.each(['Compra', 'Aporte'] as const)(
      'OQ-14 refuses a typed future date in %s on the Data field, never replacing it silently',
      async (kind) => {
        const bodies = captureBodies('/ledger/entries');
        const { user } = await openLedger();
        const modal = await openNew(user, kind);

        const date = modal.getByRole('textbox', { name: 'Data' });
        await typeDate(user, date, '19/10/2026');

        expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
        expect(date).toHaveAttribute('aria-invalid', 'true');
        // The refused date is not kept as some other date that could be saved unnoticed.
        expect(date).not.toHaveValue('18/10/2026');
        await user.click(modal.getByRole('button', { name: /^Registrar/ }));
        expect(bodies).toEqual([]);

        await typeDate(user, date, '17/10/2026');
        expect(modal.queryByText('A data não pode ser posterior a hoje.')).not.toBeInTheDocument();
      },
    );

    it.each([
      ['FUTURE_DATE', 'A data não pode ser posterior a hoje.'],
      ['CONTRACT_MATURED', 'O contrato já venceu nesta data.'],
    ] as const)('OQ-14 / OQ-1 shows %s on the Data field', async (code, message) => {
      server.use(
        http.post(url('/ledger/entries'), () => problem(422, [fieldError(code, message, 'date')])),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText(message)).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('OQ-15 shows every message when two API fields belong to the same input', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Informe um número válido.', 'execution_rate'),
            fieldError('VALIDATION_ERROR', 'Informe o PU ou a taxa.', 'input_kind'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText(/Informe um número válido\./)).toBeInTheDocument();
      expect(modal.getByText(/Informe o PU ou a taxa\./)).toBeInTheDocument();
    });

    it('OQ-15 shows an error without a field above the form', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(409, [fieldError('VALIDATION_ERROR', 'Lançamentos bloqueados no momento.')]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByRole('alert')).toHaveTextContent(
        'Lançamentos bloqueados no momento.',
      );
    });
  });

  describe('Aporte / Retirada (§6.2)', () => {
    it('§6.2 registers an aporte with its time and a positive amount', async () => {
      answerCreate(serveEntries(), {
        type: 'CASH',
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-15',
        time: '11:20:00',
        seq: 6,
        cash_amount: '2500.50',
        created_at: '2026-10-18T12:00:00-03:00',
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '11:20' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '2.500,50');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(
        await screen.findByText(
          /^Aporte registrado\. O caixa precisa ser processado a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Caixa\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        { type: 'CASH', date: '2026-10-15', time: '11:20:00', cash_amount: '2500.50' },
      ]);
      expect(await screen.findByText('+R$ 2.500,50')).toBeInTheDocument();
    });

    it('§6.2 registers a retirada: typed positive, sent as a negative amount', async () => {
      answerCreate(serveEntries(), {
        type: 'CASH',
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-15',
        time: '09:05:00',
        seq: 6,
        cash_amount: '-1000',
        created_at: '2026-10-18T12:00:00-03:00',
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Retirada');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '09:05' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000');
      await user.click(modal.getByRole('button', { name: 'Registrar retirada' }));

      expect(
        await screen.findByText(
          /^Retirada registrada\. O caixa precisa ser processado a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Caixa\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        { type: 'CASH', date: '2026-10-15', time: '09:05:00', cash_amount: '-1000' },
      ]);
      expect(await screen.findByText('-R$ 1.000,00')).toBeInTheDocument();
    });

    it('§6.2 never sends a negative or zero amount: the side gives the sign', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '-1.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));
      expect(modal.getByText('Informe um valor maior que zero.')).toBeInTheDocument();

      await user.clear(modal.getByRole('textbox', { name: 'Valor (R$)' }));
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '0,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));
      expect(modal.getByText('Informe um valor maior que zero.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });

    it('OQ-3 shows the decimal-place error of an amount on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 2 casas decimais.', 'cash_amount'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '10,505');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(await modal.findByText('Use no máximo 2 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it('OQ-14 shows FUTURE_DATE on the Data field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.', 'date'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('§6.2 rejects a value that is not a pt-BR number before sending', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1,000.50');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(modal.getByText('Informe um valor válido, como 1.234,56.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });
  });

  describe('Novo lançamento modal (§11.3)', () => {
    it('§11.3 opens one modal that switches between Operação and Caixa', async () => {
      const { user } = await openLedger();

      await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
      const modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));

      expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
      expect(modal.getByRole('radio', { name: 'Operação' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Compra' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Venda' })).not.toBeChecked();
      expect(modal.getByRole('combobox', { name: 'Contrato' })).toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar compra' })).toBeInTheDocument();

      await user.click(modal.getByRole('radio', { name: 'Caixa' }));

      expect(modal.getByRole('radio', { name: 'Aporte' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Retirada' })).not.toBeChecked();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toBeInTheDocument();
      expect(modal.queryByRole('combobox', { name: 'Contrato' })).not.toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar aporte' })).toBeInTheDocument();

      await user.click(modal.getByRole('radio', { name: 'Retirada' }));
      expect(modal.getByRole('button', { name: 'Registrar retirada' })).toBeInTheDocument();
    });

    it('§11.3 filters the contracts by asset class and finds one by its code', async () => {
      // A second class, so the filter has something to leave out.
      const dollar = {
        ...products[0],
        id: 'b0000000-0000-4000-8000-000000000001',
        code: 'DOL',
        name: 'Futuro de Dólar Comercial',
        asset_class: { id: 2, code: 'FX_FUTURE', name: 'Futuros de Moeda' },
        instrument_count: 1,
      };
      server.use(
        http.get(url('/products'), () => HttpResponse.json({ items: [...products, dollar] })),
        http.get(url('/instruments'), () =>
          HttpResponse.json({
            items: [
              ...instruments.map((i) => ({ ...i, last_reference: null })),
              {
                id: 'b0000000-0000-4000-8000-0000000000d1',
                code: 'DOLX26',
                product_id: dollar.id,
                product_code: 'DOL',
                maturity_date: '2026-12-01',
                created_at: '2026-10-01T09:00:00-03:00',
                last_reference: null,
              },
            ],
          }),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      const contract = modal.getByRole('combobox', { name: 'Contrato' });
      await waitFor(() => {
        expect(contract).toBeEnabled();
      });
      const option = (code: string) => screen.queryByRole('option', { name: code, hidden: true });

      await user.click(contract);
      expect(option('DOLX26')).toBeInTheDocument();
      expect(option('DI1F28')).toBeInTheDocument();
      await user.click(screen.getByRole('option', { name: 'DOLX26', hidden: true }));
      expect(contract).toHaveValue('DOLX26');

      await user.click(modal.getByRole('combobox', { name: 'Classe de ativo' }));
      await user.click(
        await screen.findByRole('option', { name: 'Futuros de Taxa de Juros', hidden: true }),
      );
      // DOLX26 is not of that class: it is cleared and no longer offered.
      expect(contract).toHaveValue('');
      await user.click(contract);
      expect(option('DOLX26')).not.toBeInTheDocument();
      expect(option('DI1F28')).toBeInTheDocument();

      await user.type(contract, 'F29');
      expect(option('DI1F29')).toBeInTheDocument();
      expect(option('DI1F28')).not.toBeInTheDocument();
    });

    it('§11.3 a class change keeps a contract of the chosen class', async () => {
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      await chooseContract(user, modal, 'DI1F28');

      await user.click(modal.getByRole('combobox', { name: 'Classe de ativo' }));
      await user.click(
        await screen.findByRole('option', { name: 'Futuros de Taxa de Juros', hidden: true }),
      );

      expect(modal.getByRole('combobox', { name: 'Contrato' })).toHaveValue('DI1F28');
    });
  });

  describe('Novo lançamento modal: state (§11.3)', () => {
    it('§11.3 each opening starts again at Operação → Compra with blank fields', async () => {
      const { user } = await openLedger();
      let modal = await openNew(user, 'Retirada');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000,00');
      await user.click(modal.getByRole('button', { name: 'Fechar' }));
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
      modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));

      expect(modal.getByRole('radio', { name: 'Operação' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Compra' })).toBeChecked();
      await user.click(modal.getByRole('radio', { name: 'Caixa' }));
      expect(modal.getByRole('radio', { name: 'Aporte' })).toBeChecked();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toHaveValue('');
    });

    it('OQ-15 locks the kind of entry while a save runs', async () => {
      let release: () => void = () => undefined;
      server.use(
        http.post(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      await waitFor(() => {
        expect(modal.getByRole('radio', { name: 'Operação' })).toBeDisabled();
      });
      expect(modal.getByRole('radio', { name: 'Retirada' })).toBeDisabled();
      release();
    });

    it('§12 says so on Classe de ativo when the classes fail to load; contracts still work', async () => {
      server.use(
        http.get(url('/products'), () =>
          problem(500, [fieldError('VALIDATION_ERROR', 'Erro interno.')]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      expect(
        await modal.findByText('Não foi possível carregar as classes de ativo.'),
      ).toBeInTheDocument();
      expect(modal.queryByText('Não foi possível carregar os contratos.')).not.toBeInTheDocument();
      await chooseContract(user, modal, 'DI1F28');
    });
  });
});
