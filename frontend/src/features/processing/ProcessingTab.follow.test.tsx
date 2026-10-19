import { act, waitFor } from '@testing-library/react';

import type { ProcessingRequest } from '@/api/contract';
import { job, processingRequests } from '@/test/msw/fixtures';
import { countReads, serveJobs } from '@/test/msw/server';
import { renderApp } from '@/test/render';

import { PAGE, serveWith, findJobRow } from './processingTab.support';

describe('Processamentos: polling (§11.1, §12)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§12 does not poll when no job is active', async () => {
    const jobs = serveJobs([...processingRequests]);
    renderApp(PAGE);
    await findJobRow('01/10/2026 a 05/10/2026', 'Falhou');
    const before = jobs.polls;

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(jobs.polls).toBe(before);
  });

  it('§12 polls every 2 s while a job is active, and stops once it has finished', async () => {
    const jobs = serveWith(job());
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    const before = jobs.polls;

    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(jobs.polls).toBe(before + 1);

    // QUEUED → RUNNING (17/10) → RUNNING (18/10) → COMPLETED_WITH_ISSUES; no dispatch (OQ-46).
    const started = { status: 'RUNNING', started_at: '2026-10-18T10:00:02-03:00' } as const;
    jobs.items = [job(started), ...processingRequests];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    const running = await findJobRow('17/10/2026 a 18/10/2026', 'Processando');
    expect(running.getByText('0 / 2 dias')).toBeInTheDocument();
    jobs.items = [job({ ...started, progress_date: '2026-10-17' }), ...processingRequests];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', '1 / 2 dias');
    const issuesBefore = issueReads.count;
    jobs.items = [
      job({
        ...started,
        status: 'COMPLETED_WITH_ISSUES',
        progress_date: '2026-10-18',
        finished_at: '2026-10-18T10:00:09-03:00',
      }),
      ...processingRequests,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    await findJobRow('17/10/2026 a 18/10/2026', 'Concluído com pendências');

    // The finished job refreshes the published results and the pendências once.
    await waitFor(() => {
      expect(issueReads.count).toBe(issuesBefore + 1);
    });
    const afterFinish = jobs.polls;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(jobs.polls).toBe(afterFinish);
    expect(issueReads.count).toBe(issuesBefore + 1);
  });
});

describe('Processamentos: a job that finished between two reads (§10.4)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 refreshes the results when a new job is first seen already finished', async () => {
    const jobs = serveWith(job());
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    await waitFor(() => {
      expect(issueReads.count).toBeGreaterThan(0);
    });
    const before = issueReads.count;

    // Queued and finished elsewhere between two polls.
    jobs.items = [
      job({
        id: 'bb000000-0000-4000-8000-000000000001',
        start_date: '2026-10-15',
        end_date: '2026-10-15',
        status: 'COMPLETED',
        created_at: '2026-10-18T11:00:00-03:00',
        progress_date: '2026-10-15',
      }),
      ...jobs.items,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await findJobRow('15/10/2026 a 15/10/2026', 'Concluído');
    await waitFor(() => {
      expect(issueReads.count).toBe(before + 1);
    });
  });
});

describe('Processamentos: UTC timestamps (OQ-46, #93)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§10.4 compares creation times as instants: an older job in UTC is not news', async () => {
    const jobs = serveWith(job({ created_at: '2026-10-18T22:00:00-03:00' })); // 19/10 01:00 UTC
    const issueReads = countReads('/processing/issues');
    renderApp(PAGE);
    await findJobRow('17/10/2026 a 18/10/2026', 'Na fila');
    await waitFor(() => {
      expect(issueReads.count).toBeGreaterThan(0);
    });
    const before = issueReads.count;

    // Finished, but created before the newest job seen: its string sorts later, its instant not.
    // Newest first by instant, so it comes second.
    const [newest, ...older] = jobs.items;
    jobs.items = [
      newest as ProcessingRequest,
      job({
        id: 'bb000000-0000-4000-8000-000000000001',
        start_date: '2026-10-15',
        end_date: '2026-10-15',
        status: 'COMPLETED',
        created_at: '2026-10-19T00:59:00Z',
        progress_date: '2026-10-15',
      }),
      ...older,
    ];
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    await findJobRow('15/10/2026 a 15/10/2026', 'Concluído');
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(issueReads.count).toBe(before);
  });
});
