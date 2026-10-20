import { act, screen, waitFor } from '@testing-library/react';

import { job } from '@/test/msw/fixtures';
import { countReads, serveJobs } from '@/test/msw/server';
import { renderApp } from '@/test/render';

// A job's end refreshes the published results on every screen, not only while Central de
// Controle is open (§10.4, §12). The job list is polled once per interval, whichever screen is
// open, and only while a job is queued or running.

/** A run of 17/10 to 18/10 that the API reports queued, then running, then finished. */
const QUEUED = job();
const RUNNING = job({ status: 'RUNNING', started_at: '2026-10-18T10:00:02-03:00' });
const FINISHED = job({
  status: 'COMPLETED_WITH_ISSUES',
  progress_date: '2026-10-18',
  started_at: '2026-10-18T10:00:02-03:00',
  finished_at: '2026-10-18T10:00:09-03:00',
});

describe('job watcher (§10.4, §12)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 refreshes Carteira when a job ends while Central de Controle is closed', async () => {
    const jobs = serveJobs([QUEUED]);
    const summaryReads = countReads('/portfolio/summary');
    renderApp('/carteira');
    await waitFor(() => {
      expect(summaryReads.count).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(jobs.polls).toBeGreaterThan(0);
    });
    const before = summaryReads.count;

    // QUEUED → RUNNING → final; no dispatch (OQ-46).
    jobs.items = [RUNNING];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    jobs.items = [FINISHED];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await waitFor(() => {
      expect(summaryReads.count).toBe(before + 1);
    });
  });

  it('§10.4 refreshes the Lançamentos cash strip when a job ends there', async () => {
    const jobs = serveJobs([QUEUED]);
    const summaryReads = countReads('/portfolio/summary');
    renderApp('/lancamentos?inicio=2026-10-14&fim=2026-10-16');
    await screen.findByText(/lançamentos? encontrados?$/);
    await waitFor(() => {
      expect(summaryReads.count).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(jobs.polls).toBeGreaterThan(0);
    });
    const before = summaryReads.count;

    jobs.items = [FINISHED];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    // Caixa D0 and Caixa D−1: one summary each (OQ-19).
    await waitFor(() => {
      expect(summaryReads.count).toBe(before + 2);
    });
  });

  it('§12 does not poll the jobs from another screen when no job is active', async () => {
    const jobs = serveJobs([FINISHED]);
    renderApp('/carteira');
    await waitFor(() => {
      expect(jobs.polls).toBe(1);
    });

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(jobs.polls).toBe(1);
  });

  it('§12 polls once per interval with Central de Controle open, not once per reader', async () => {
    const jobs = serveJobs([QUEUED]);
    renderApp('/central-de-controle?tab=processamentos');
    await screen.findByText('Na fila');
    await act(() => vi.advanceTimersByTimeAsync(100));
    const before = jobs.polls;

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(jobs.polls).toBe(before + 5);
  });
});
