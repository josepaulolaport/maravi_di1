import { screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';

import { preview, processingRequests } from '@/test/msw/fixtures';
import { url, type User, fieldError, problem } from '@/test/helpers';
import { server, serveJobs } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

import {
  PAGE,
  servePreview,
  previewOf,
  answerEnqueue,
  field,
  findJobRow,
  typeRange,
} from '@/test/screens/processing';

describe('Processamentos: request (§11.1, OQ-20)', () => {
  it('§11.1 keeps the request button disabled until the range is complete and ordered', async () => {
    const { user } = renderRoute(PAGE);

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
    renderRoute(`${PAGE}&inicio=2026-10-16&fim=2026-10-18`);

    expect(await screen.findByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveValue('18/10/2026');
    expect(screen.getByRole('button', { name: 'Solicitar processamento' })).toBeEnabled();
  });

  it('OQ-14 ignores a future date in the link', async () => {
    renderRoute(`${PAGE}&inicio=2026-10-16&fim=2099-01-01`);

    expect(await screen.findByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
    expect(screen.getByRole('textbox', { name: 'Data final' })).toHaveValue('');
    expect(
      await screen.findByText('A data 01/01/2099 não pode ser posterior a hoje e foi ignorada.'),
    ).toBeInTheDocument();
  });

  it('OQ-14 OQ-29 refuses a typed future end date on its field', async () => {
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-16&fim=2026-10-17`);

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
    servePreview(preview);
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-15&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-17&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
      const { user } = renderRoute(`${PAGE}&inicio=2026-10-18&fim=2026-10-18`);

      await user.click(await screen.findByRole('radio', { name: scope }));
      await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-17&fim=2026-10-18`);
    expect(await screen.findByRole('radio', { name: 'Tudo' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Caixa' }));
    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
    expect(await modal.findByText('Processado (16/10)')).toBeInTheDocument();
    expect(field(modal, 'Escopo').getByText('Caixa')).toBeInTheDocument();
    expect(modal.queryByRole('group', { name: 'Estado anterior das posições' })).toBeNull();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-21 keeps the scope in the URL (escopo) and prefills it from there', async () => {
    const { user, router } = renderRoute(`${PAGE}&escopo=posicoes`);
    expect(await screen.findByRole('radio', { name: 'Posições' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Caixa' }));

    expect(router.state.location.search).toContain('escopo=caixa');
  });

  it('OQ-21 sends the chosen scope and shows it in the history', async () => {
    servePreview(
      previewOf('2026-10-17', '2026-10-18', '2026-10-16', 2, 'PROCESSED', 'NOT_PROCESSED', 'CASH'),
    );
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-17&fim=2026-10-18&escopo=caixa`);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Solicitar processamento' });
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
    const { user } = renderRoute(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await typeRange(user, '17/10/2026', '18/10/2026');
    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Solicitar processamento' });
    await within(dialog).findByText('17/10/2026 a 18/10/2026');
    await user.click(within(dialog).getByRole('button', { name: 'Confirmar processamento' }));

    const row = await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    expect(row.getByText('0 / 2 dias')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Solicitar processamento' })).toBeNull();
    });
    expect(screen.getByText('6 processamentos encontrados')).toBeInTheDocument();
  });

  it('§11.1 closes the confirmation with "Cancelar" without queueing', async () => {
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');

    await user.click(screen.getByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Solicitar processamento' });
    await within(dialog).findByText('3');
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Solicitar processamento' })).toBeNull();
    });
    expect(screen.getByText('5 processamentos encontrados')).toBeInTheDocument();
    expect(bodies).toEqual([]);
  });
});

describe('Processamentos: request safety (§10.2, OQ-15)', () => {
  async function openConfirmation(user: User) {
    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));
    const dialog = await screen.findByRole('dialog', { name: 'Solicitar processamento' });
    await within(dialog).findByText('3');
    return within(dialog);
  }

  it('§10.2 queues one job on a double click', async () => {
    const bodies = answerEnqueue(serveJobs([...processingRequests]));
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

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
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    let dialog = await openConfirmation(user);
    await user.click(dialog.getByRole('button', { name: 'Confirmar processamento' }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Solicitar processamento' })).toBeInTheDocument();
    open();
    await findJobRow('14/10/2026 a 16/10/2026', 'Na fila');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Solicitar processamento' })).toBeNull();
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
        problem(422, [fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.')]),
      ),
    );
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    const dialog = await openConfirmation(user);
    await user.click(dialog.getByRole('button', { name: 'Confirmar processamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'A data não pode ser posterior a hoje.',
    );
    expect(screen.getByRole('dialog', { name: 'Solicitar processamento' })).toBeInTheDocument();
    expect(screen.getByText('5 processamentos encontrados')).toBeInTheDocument();
  });
});

describe('Processamentos: preview failure (OQ-15)', () => {
  it('OQ-15 shows the API message when the preview fails, and cannot confirm', async () => {
    server.use(
      http.get(url('/processing/preview'), () =>
        problem(422, [fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.')]),
      ),
    );
    const { user } = renderRoute(`${PAGE}&inicio=2026-10-14&fim=2026-10-16`);

    await user.click(await screen.findByRole('button', { name: 'Solicitar processamento' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
    expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Confirmar processamento' })).toBeDisabled();
  });
});
