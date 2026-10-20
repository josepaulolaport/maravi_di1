import { screen, waitFor, within } from '@testing-library/react';

import { job } from '@/test/msw/fixtures';
import { renderRoute } from '@/test/render';

import { PAGE, serveWith, RUNNING, field, openMenu } from '@/test/screens/processing';

describe('Processamentos: details (§11.1, §10.4)', () => {
  it('OQ-46 the details of a running job with a cancel asked show Cancelando and no cancel action', async () => {
    serveWith(job({ ...RUNNING, cancel_requested_at: '2026-10-18T13:05:00Z' }));
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Cancelando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Cancelando');
    expect(field(modal, 'Data em processamento').getByText('18/10/2026')).toBeInTheDocument();
    expect(modal.queryByRole('button', { name: 'Cancelar processamento' })).not.toBeInTheDocument();
  });

  it('§10.2 from the details, "Cancelar processamento" moves the focus into the cancel dialog', async () => {
    serveWith(job(RUNNING));
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const details = within(
      await screen.findByRole('dialog', { name: 'Detalhes do processamento' }),
    );
    await user.click(details.getByRole('button', { name: 'Cancelar processamento' }));

    const cancel = await screen.findByRole('dialog', { name: 'Cancelar processamento?' });
    await waitFor(() => {
      expect(cancel).toContainElement(document.activeElement as HTMLElement);
    });
  });

  it('§11.1 OQ-23 OQ-44 shows a failed run: times in Brasília, days, the date it failed on, its error', async () => {
    const { user, router } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '01/10/2026 a 05/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Falhou');
    expect(modal.getByText('7f3c9a04')).toBeInTheDocument();
    const field = (label: string) => within(modal.getByRole('group', { name: label }));
    expect(field('Período solicitado').getByText('01/10/2026 a 05/10/2026')).toBeInTheDocument();
    expect(field('Criação').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Início').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Finalização').getByText('14/10/2026 08:00')).toBeInTheDocument();
    expect(field('Total de dias').getByText('5')).toBeInTheDocument();
    expect(field('Dias concluídos').getByText('0')).toBeInTheDocument();
    expect(field('Dias restantes').getByText('5')).toBeInTheDocument();
    expect(field('Data com erro').getByText('01/10/2026')).toBeInTheDocument();
    // A technical failure of no chain (OQ-44): its date, no chain, the API's message.
    expect(modal.getByRole('alert')).toHaveTextContent('Erro técnico ao processar a data.');
    expect(modal.queryByRole('group', { name: 'Cadeia com erro' })).not.toBeInTheDocument();
    expect(
      modal.getByText(
        'Nenhuma data deste processamento foi publicada; os resultados anteriores permanecem inalterados.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByRole('progressbar')).not.toBeInTheDocument();

    await user.click(modal.getByRole('button', { name: 'Solicitar novo processamento' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-01&fim=2026-10-05&escopo=tudo',
    );
  });

  it('OQ-23 says a run cancelled before its first date published nothing', async () => {
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '10/10/2026 a 12/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(
      modal.getByText(
        'Nenhuma data deste processamento foi publicada; os resultados anteriores permanecem inalterados.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('OQ-23 says which dates a run cancelled midway kept, and offers a new request', async () => {
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '14/10/2026 a 16/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Cancelado');
    expect(field(modal, 'Finalização').getByText('16/10/2026 17:31')).toBeInTheDocument();
    expect(field(modal, 'Dias concluídos').getByText('2')).toBeInTheDocument();
    expect(
      modal.getByText(
        'As datas de 14/10/2026 a 15/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Solicitar novo processamento' })).toBeInTheDocument();
  });

  /** A Tudo run where positions failed on 17/10 and cash went on to the end (OQ-36). */
  const PARTIAL = {
    status: 'COMPLETED_WITH_ISSUES',
    start_date: '2026-10-16',
    progress_date: '2026-10-18',
    error_code: 'POSITIONS_PREDECESSOR_MISSING',
    error_message: 'Dia anterior não processado',
    failed_date: '2026-10-17',
    failed_chain: 'POSITIONS',
    dispatched_at: '2026-10-18T10:00:01-03:00',
    started_at: '2026-10-18T10:00:02-03:00',
    finished_at: '2026-10-18T10:00:09-03:00',
  } as const;

  it('OQ-36 OQ-40 a Concluído com pendências Tudo run where a chain failed shows the error, its date and chain', async () => {
    serveWith(job(PARTIAL));
    const { user } = renderRoute(PAGE);

    const menu = within(
      await openMenu(user, '16/10/2026 a 18/10/2026', 'Concluído com pendências'),
    );
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Solicitar novo processamento (Posições)',
    ]);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Dia anterior não processado');
    expect(field(modal, 'Data com erro').getByText('17/10/2026')).toBeInTheDocument();
    expect(field(modal, 'Cadeia com erro').getByText('Posições')).toBeInTheDocument();
    // What each chain published (OQ-36 item 1): positions stopped on 17/10, cash reached the end.
    expect(
      modal.getByText('Caixa: as datas de 16/10/2026 a 18/10/2026 foram publicadas.'),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 16/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
  });

  it('OQ-36 a Falhou Tudo run where the chains failed on different dates says what each published', async () => {
    serveWith(
      job({
        ...PARTIAL,
        status: 'FAILED',
        progress_date: '2026-10-17',
        error_code: 'PROCESSING_ERROR',
        error_message: 'Falha nas posições de 17/10/2026.',
      }),
    );
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '16/10/2026 a 18/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(
      modal.getByText(
        'Caixa: as datas de 16/10/2026 a 17/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 16/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByText(/^As datas de/)).not.toBeInTheDocument();
  });

  it('OQ-40 the failed-chain retry prefills that chain from failed_date to the original end', async () => {
    serveWith(job(PARTIAL));
    const { user, router } = renderRoute(PAGE);

    const menu = within(
      await openMenu(user, '16/10/2026 a 18/10/2026', 'Concluído com pendências'),
    );
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    await user.click(
      modal.getByRole('button', { name: 'Solicitar novo processamento (Posições)' }),
    );

    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-17&fim=2026-10-18&escopo=posicoes',
    );
    expect(screen.getByRole('radio', { name: 'Posições' })).toBeChecked();
  });

  it('OQ-36 OQ-40 a Cancelado Tudo run after a chain failed keeps the error and offers both retries', async () => {
    serveWith(
      job({
        status: 'CANCELLED',
        start_date: '2026-10-15',
        progress_date: '2026-10-16',
        error_code: 'PROCESSING_ERROR',
        error_message: 'Falha ao processar o caixa de 16/10/2026.',
        failed_date: '2026-10-16',
        failed_chain: 'CASH',
        started_at: '2026-10-18T10:00:02-03:00',
        finished_at: '2026-10-18T10:00:09-03:00',
        cancel_requested_at: '2026-10-18T10:00:05-03:00',
      }),
    );
    const { user, router } = renderRoute(PAGE);

    let menu = within(await openMenu(user, '15/10/2026 a 18/10/2026', 'Cancelado'));
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'Ver detalhes',
      'Solicitar novo processamento',
      'Solicitar novo processamento (Caixa)',
    ]);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Falha ao processar o caixa de 16/10/2026.');
    expect(field(modal, 'Cadeia com erro').getByText('Caixa')).toBeInTheDocument();
    // Cash read Erro on 16/10, so only positions published it (OQ-36 item 10).
    expect(
      modal.getByText(
        'Caixa: as datas de 15/10/2026 a 15/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(
      modal.getByText(
        'Posições: as datas de 15/10/2026 a 16/10/2026 foram publicadas; as seguintes não foram processadas.',
      ),
    ).toBeInTheDocument();
    expect(modal.queryByText(/^As datas de/)).not.toBeInTheDocument();
    await user.click(modal.getByRole('button', { name: 'Solicitar novo processamento' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-17&fim=2026-10-18&escopo=tudo',
    );

    menu = within(await openMenu(user, '15/10/2026 a 18/10/2026', 'Cancelado'));
    await user.click(menu.getByRole('menuitem', { name: 'Solicitar novo processamento (Caixa)' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-16&fim=2026-10-18&escopo=caixa',
    );
  });

  it('OQ-36 a Concluído com pendências run with only missing prices shows no error and no retry', async () => {
    const { user } = renderRoute(PAGE);

    const menu = within(
      await openMenu(user, '14/10/2026 a 16/10/2026', 'Concluído com pendências'),
    );
    expect(menu.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Ver detalhes']);
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.queryByRole('alert')).not.toBeInTheDocument();
    expect(modal.queryByRole('group', { name: 'Cadeia com erro' })).not.toBeInTheDocument();
    expect(modal.queryByRole('button', { name: /Solicitar novo/ })).not.toBeInTheDocument();
  });

  it('OQ-47 a run that failed writing its end shows no error date and asks the whole range again', async () => {
    // Every date committed, then recording the run's end failed (interfaces "Failure and recovery").
    serveWith(
      job({
        status: 'FAILED',
        start_date: '2026-10-16',
        progress_date: '2026-10-18',
        error_code: 'PROCESSING_ERROR',
        error_message: 'Erro técnico ao processar a data.',
        started_at: '2026-10-18T10:00:02-03:00',
        finished_at: '2026-10-18T10:00:09-03:00',
      }),
    );
    const { user, router } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '16/10/2026 a 18/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Erro técnico ao processar a data.');
    expect(modal.queryByRole('group', { name: 'Data com erro' })).not.toBeInTheDocument();
    expect(modal.queryByText('19/10/2026')).not.toBeInTheDocument();

    await user.click(modal.getByRole('button', { name: 'Solicitar novo processamento' }));
    expect(router.state.location.search).toBe(
      '?tab=processamentos&inicio=2026-10-16&fim=2026-10-18&escopo=tudo',
    );
  });

  it('§11.1 still shows an error box for a failed job without a message', async () => {
    serveWith(
      job({
        status: 'FAILED',
        error_code: 'PROCESSING_ERROR',
        finished_at: '2026-10-18T10:01:00-03:00',
      }),
    );
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Falhou'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('alert')).toHaveTextContent('Falha técnica inesperada.');
  });

  it('§11.1 shows a completed job without the unpublished notice or actions', async () => {
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '14/10/2026 a 15/10/2026', 'Concluído'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    expect(modal.getByRole('status')).toHaveTextContent('Concluído');
    expect(modal.queryByText(/Nenhum dia deste processamento/)).not.toBeInTheDocument();
    expect(
      modal.queryByRole('button', { name: /Solicitar novo|Cancelar/ }),
    ).not.toBeInTheDocument();
  });

  it('§10.4 follows a running job: the date being processed, progress and the cancel actions', async () => {
    serveWith(job({ ...RUNNING, created_at: '2026-10-18T09:58:00-03:00' }));
    const { user } = renderRoute(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Ver detalhes' }));

    const modal = within(await screen.findByRole('dialog', { name: 'Detalhes do processamento' }));
    const field = (label: string) => within(modal.getByRole('group', { name: label }));
    expect(field('Data em processamento').getByText('18/10/2026')).toBeInTheDocument();
    expect(field('Criação').getByText('18/10/2026 09:58')).toBeInTheDocument();
    expect(field('Início').getByText('18/10/2026 10:00')).toBeInTheDocument();
    expect(field('Finalização').getByText('—')).toBeInTheDocument();
    expect(field('Dias restantes').getByText('1')).toBeInTheDocument();
    expect(modal.getByRole('progressbar', { name: 'Progresso' })).toBeInTheDocument();
    expect(modal.getByRole('button', { name: 'Cancelar processamento' })).toBeInTheDocument();
    // OQ-30: there is no cancel-and-replace.
    expect(modal.queryByRole('button', { name: /criar novo/ })).not.toBeInTheDocument();
  });
});
