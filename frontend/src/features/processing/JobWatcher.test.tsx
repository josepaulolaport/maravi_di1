import { act, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { ProcessingRequest } from '@/api/contract';
import { db } from '@/api/mocks/db';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

// A job's end refreshes the published results on every screen, not only while Central de
// Controle is open (§10.4, §12). The job list is polled once per interval, whichever screen is
// open, and only while a job is queued or running.

/**
 * Serves the job list from the mock store without advancing the fake worker (each mock poll
 * advances it one step), except for the polls released with `release(n)`. Counts the polls.
 */
function holdWorker() {
  let released = 0;
  const polls = { count: 0 };
  server.use(
    http.get(url('/processing/requests'), () => {
      polls.count += 1;
      if (released > 0) {
        released -= 1;
        return undefined; // falls through to the mock handler, which advances the worker
      }
      const items = [...db.requests].sort((a, b) => b.created_at.localeCompare(a.created_at));
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
  return {
    polls,
    release: (n = 1) => {
      released += n;
    },
  };
}

/** Counts the reads of one /portfolio endpoint. */
function countReads(path: string) {
  const reads = { count: 0 };
  server.use(
    http.get(url(path), () => {
      reads.count += 1;
      return undefined;
    }),
  );
  return reads;
}

function seedQueuedJob(): ProcessingRequest {
  const job: ProcessingRequest = {
    id: 'aa000000-0000-4000-8000-000000000001',
    scope: 'ALL',
    start_date: '2026-10-17',
    end_date: '2026-10-18',
    status: 'QUEUED',
    progress_date: null,
    error_code: null,
    error_message: null,
    failed_date: null,
    failed_chain: null,
    created_at: '2026-10-18T10:00:00-03:00',
    updated_at: '2026-10-18T10:00:00-03:00',
    dispatched_at: null,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
  };
  db.requests.push(job);
  return job;
}

describe('job watcher (§10.4, §12)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 refreshes Carteira when a job ends while Central de Controle is closed', async () => {
    const job = seedQueuedJob();
    const worker = holdWorker();
    const summaryReads = countReads('/portfolio/summary');
    renderApp('/carteira');
    await waitFor(() => {
      expect(summaryReads.count).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(worker.polls.count).toBeGreaterThan(0);
    });
    const before = summaryReads.count;

    // QUEUED → RUNNING (17/10) → RUNNING (18/10) → final; no dispatch (OQ-46).
    worker.release(3);
    for (let i = 0; i < 3; i += 1) await act(() => vi.advanceTimersByTimeAsync(2_000));

    expect(isFinalStatus(job.status)).toBe(true);
    await waitFor(() => {
      expect(summaryReads.count).toBe(before + 1);
    });
  });

  it('§10.4 refreshes the Lançamentos cash strip when a job ends there', async () => {
    seedQueuedJob();
    const worker = holdWorker();
    const summaryReads = countReads('/portfolio/summary');
    renderApp('/lancamentos?inicio=2026-10-14&fim=2026-10-16');
    await screen.findByText(/lançamentos? encontrados?$/);
    await waitFor(() => {
      expect(summaryReads.count).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(worker.polls.count).toBeGreaterThan(0);
    });
    const before = summaryReads.count;

    worker.release(3);
    for (let i = 0; i < 3; i += 1) await act(() => vi.advanceTimersByTimeAsync(2_000));

    // Caixa D0 and Caixa D−1: one summary each (OQ-19).
    await waitFor(() => {
      expect(summaryReads.count).toBe(before + 2);
    });
  });

  it('§12 does not poll the jobs from another screen when no job is active', async () => {
    const worker = holdWorker();
    renderApp('/carteira');
    await waitFor(() => {
      expect(worker.polls.count).toBe(1);
    });

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(worker.polls.count).toBe(1);
  });

  it('§12 polls once per interval with Central de Controle open, not once per reader', async () => {
    seedQueuedJob();
    const worker = holdWorker();
    renderApp('/central-de-controle?tab=processamentos');
    await screen.findByText('Na fila');
    await act(() => vi.advanceTimersByTimeAsync(100));
    const before = worker.polls.count;

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(worker.polls.count).toBe(before + 5);
  });
});

function isFinalStatus(status: ProcessingRequest['status']): boolean {
  return !['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'].includes(status);
}
