import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { job, processingRequests } from '@/test/msw/fixtures';
import { url } from '@/test/msw/handlers';
import { server } from '@/test/msw/server';
import { renderApp } from '@/test/render';

import {
  PAGE,
  problemResponse,
  answerCancel,
  serveWith,
  RUNNING,
  jobRow,
  findJobRow,
  openMenu,
} from './processingTab.support';

describe('Processamentos: cancel (§10.2)', () => {
  it('§10.2 cancels a queued job at once, after confirmation', async () => {
    const jobs = serveWith(job());
    const cancels = answerCancel(
      jobs,
      job({
        status: 'CANCELLED',
        cancel_requested_at: '2026-10-18T10:05:00-03:00',
        finished_at: '2026-10-18T10:05:00-03:00',
      }),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));

    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    expect(dialog.getByText('aa000000')).toBeInTheDocument();
    expect(dialog.getByText('17/10/2026 a 18/10/2026')).toBeInTheDocument();
    expect(dialog.getByText('0 / 2 dias')).toBeInTheDocument();
    expect(dialog.getByText('Na fila')).toBeInTheDocument();
    // A queued run is cancelled at once (interfaces "Processing"): no date is in progress.
    expect(
      dialog.getByText(
        'O processamento ainda não começou e será cancelado imediatamente. Nenhuma data será processada.',
      ),
    ).toBeInTheDocument();
    expect(dialog.queryByText(/ao fim da data em andamento/)).toBeNull();
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado');
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Cancelar processamento?' })).toBeNull();
    });
    expect(cancels.count).toBe(1);
  });

  it('§10.2 goes back without cancelling', async () => {
    const jobs = serveWith(job());
    const cancels = answerCancel(jobs, job({ status: 'CANCELLED' }));
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Voltar' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Cancelar processamento?' })).toBeNull();
    });
    expect(cancels.count).toBe(0);
    expect(jobRow('17/10/2026 a 18/10/2026', 'Na fila')).toBeTruthy();
  });

  it('§10.2 OQ-23 OQ-46 cancels a running job cooperatively: Cancelando, then Cancelado', async () => {
    // On 17/10 of 17–18/10: the current date commits, 18/10 is not processed. (A cancel during
    // the last date would let the run complete, OQ-26 item 9.)
    const running = job({ ...RUNNING, progress_date: null });
    const jobs = serveWith(running);
    // The API keeps the run RUNNING with cancel_requested_at set (OQ-46).
    answerCancel(jobs, { ...running, cancel_requested_at: '2026-10-18T10:05:00-03:00' });
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    expect(
      dialog.getByText(
        'O processamento será interrompido ao fim da data em andamento. As datas já processadas continuam publicadas; as seguintes não serão processadas.',
      ),
    ).toBeInTheDocument();
    expect(dialog.queryByText(/cancelado imediatamente/)).toBeNull();
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    const row = await findJobRow('17/10/2026 a 18/10/2026', 'Cancelando');
    expect(row.queryByText('Processando')).not.toBeInTheDocument();
    // 17/10 commits; the run ends CANCELLED on the next poll.
    jobs.items = [
      job({
        ...RUNNING,
        status: 'CANCELLED',
        cancel_requested_at: '2026-10-18T10:05:00-03:00',
        finished_at: '2026-10-18T10:05:30-03:00',
      }),
      ...processingRequests,
    ];
    await findJobRow('17/10/2026 a 18/10/2026', 'Cancelado', 3_000);
  }, 10_000);

  it('OQ-46 shows the API message when a cancel was already asked', async () => {
    serveWith(job({ ...RUNNING, progress_date: null }));
    // Cancelled elsewhere in the meantime: the API refuses a second cancel.
    server.use(
      http.post(url('/processing/requests/:id/cancel'), () =>
        problemResponse(
          409,
          'JOB_NOT_CANCELLABLE',
          'O cancelamento deste processamento já foi solicitado.',
        ),
      ),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Processando'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'O cancelamento deste processamento já foi solicitado.',
    );
  });

  it('OQ-15 shows the 409 message when the job can no longer be cancelled', async () => {
    serveWith(job());
    server.use(
      http.post(url('/processing/requests/:id/cancel'), () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Conflito',
            status: 409,
            errors: [
              {
                code: 'JOB_NOT_CANCELLABLE',
                message: 'Este processamento já foi encerrado e não pode ser cancelado.',
                field: null,
              },
            ],
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    const { user } = renderApp(PAGE);

    const menu = within(await openMenu(user, '17/10/2026 a 18/10/2026', 'Na fila'));
    await user.click(menu.getByRole('menuitem', { name: 'Cancelar processamento' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cancelar processamento?' }));
    await user.click(dialog.getByRole('button', { name: 'Confirmar cancelamento' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'Este processamento já foi encerrado e não pode ser cancelado.',
    );
  });
});
