import type { ProcessingRequest, ProcessingScope } from '../contract';
import { ledgerApi, portfolioApi, processingApi } from '../endpoints';
import { IDS } from './fixtures';

// OQ-23 and OQ-26 (docs/open-questions.md, PR #43): a run processes its dates in calendar order
// and publishes each one in its own step; every date has one status per chain (Atualizado,
// Atualizado com pendências, Desatualizado, Processando, Erro, Não processado), and a write
// marks the dates that have a status stale from its date. The fake worker advances one step
// per read of a job: dispatch, then one date per read. Fixture scenario: 14–16/10 published for
// both chains; cash fresh; positions fresh on 14 and 15, stale on 16 (price corrected).

const FINAL = ['COMPLETED', 'COMPLETED_WITH_ISSUES', 'CANCELLED', 'FAILED'];

const poll = (job: ProcessingRequest) => processingApi.getRequest(job.id);

async function polls(job: ProcessingRequest, n: number): Promise<ProcessingRequest> {
  let current = job;
  for (let i = 0; i < n; i += 1) current = await poll(job);
  return current;
}

async function finish(job: ProcessingRequest): Promise<ProcessingRequest> {
  for (let i = 0; i < 50; i += 1) {
    const current = await poll(job);
    if (FINAL.includes(current.status)) return current;
  }
  throw new Error('the job never finished');
}

const enqueue = (start: string, end: string, scope: ProcessingScope) =>
  processingApi.enqueue({ start_date: start, end_date: end, scope });

async function status(date: string) {
  const { cash, positions } = await portfolioApi.getSummary(date);
  return { cash: cash.status, positions: positions.status };
}

const deposit = (date: string) =>
  ledgerApi.createEntry({ type: 'CASH', date, time: '12:00:00', cash_amount: '1000.00' });

describe('OQ-23 the run (eight statuses, per-date progress)', () => {
  it('OQ-23 a run carries start_date, end_date and progress_date, with no day counters', async () => {
    const job = await enqueue('2026-10-14', '2026-10-15', 'ALL');

    expect(job).toMatchObject({
      scope: 'ALL',
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      status: 'QUEUED',
      progress_date: null,
    });
    expect(job.updated_at).toEqual(expect.any(String));
    for (const gone of ['requested_start_date', 'processed_days', 'total_days']) {
      expect(job).not.toHaveProperty(gone);
    }
  });

  it('OQ-23 publishes each date as it commits; the date being processed reads Processando', async () => {
    const job = await enqueue('2026-10-14', '2026-10-15', 'ALL');

    // dispatch, start (14/10 Processando), commit 14/10 (15/10 Processando)
    expect(await polls(job, 2)).toMatchObject({ status: 'RUNNING', progress_date: null });
    expect(await status('2026-10-14')).toMatchObject({ cash: 'RUNNING', positions: 'RUNNING' });
    expect(await polls(job, 1)).toMatchObject({ status: 'RUNNING', progress_date: '2026-10-14' });
    expect(await status('2026-10-14')).toEqual({ cash: 'FRESH', positions: 'FRESH' });
    expect(await status('2026-10-15')).toMatchObject({ cash: 'RUNNING', positions: 'RUNNING' });

    expect(await finish(job)).toMatchObject({
      status: 'COMPLETED',
      progress_date: '2026-10-15',
    });
    expect(await status('2026-10-15')).toEqual({ cash: 'FRESH', positions: 'FRESH' });
  });

  it('OQ-23 a cancel keeps the dates committed, the current one included; later dates are untouched', async () => {
    const job = await enqueue('2026-10-14', '2026-10-16', 'POSITIONS');
    await polls(job, 3); // 14/10 committed, 15/10 being processed

    await processingApi.cancel(job.id);

    expect(await finish(job)).toMatchObject({ status: 'CANCELLED', progress_date: '2026-10-15' });
    expect((await status('2026-10-15')).positions).toBe('FRESH');
    expect((await status('2026-10-16')).positions).toBe('STALE');
  });

  it.each<[ProcessingScope, string, string]>([
    ['CASH', '2026-10-15', 'COMPLETED'],
    ['POSITIONS', '2026-10-16', 'COMPLETED_WITH_ISSUES'],
  ])(
    'OQ-26 a cancel during the last date lets a %s run end as it would have (%s → %s)',
    async (scope, date, ending) => {
      const job = await enqueue(date, date, scope);
      await polls(job, 2); // the only date is being processed

      await processingApi.cancel(job.id);

      expect(await finish(job)).toMatchObject({ status: ending, progress_date: date });
    },
  );

  it('OQ-23 a failure at a date: that date reads Erro, earlier ones stay published, later ones untouched', async () => {
    // The fake cannot recalculate a date whose inputs changed since the seed (15/10 on).
    await deposit('2026-10-15');

    const job = await finish(await enqueue('2026-10-14', '2026-10-16', 'CASH'));

    expect(job).toMatchObject({
      status: 'FAILED',
      progress_date: '2026-10-14',
      error_code: 'MOCK_INPUTS_CHANGED',
    });
    expect((await status('2026-10-14')).cash).toBe('FRESH');
    expect((await status('2026-10-15')).cash).toBe('FAILED');
    expect((await status('2026-10-16')).cash).toBe('STALE');
  });

  it('OQ-23 a run ends COMPLETED_WITH_ISSUES when a date it wrote is stale or has issues', async () => {
    // 17/10 follows a stale 16/10 for positions: it is written STALE.
    expect((await finish(await enqueue('2026-10-17', '2026-10-17', 'POSITIONS'))).status).toBe(
      'COMPLETED_WITH_ISSUES',
    );
    expect((await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'))).status).toBe(
      'COMPLETED',
    );
  });

  it('OQ-20 there is no SUPERSEDED: a write during a run never stops it', async () => {
    const job = await enqueue('2026-10-14', '2026-10-15', 'POSITIONS');
    await polls(job, 2);

    await deposit('2026-10-14');

    expect((await finish(job)).status).toBe('COMPLETED');
  });
});

describe('OQ-23 the status of a date, per chain', () => {
  it('OQ-23 a date after a stale one is written STALE, with a STALE_PREDECESSOR issue on that date', async () => {
    await finish(await enqueue('2026-10-17', '2026-10-18', 'POSITIONS'));

    expect((await status('2026-10-17')).positions).toBe('STALE');
    expect((await status('2026-10-18')).positions).toBe('STALE');
    const stale = (await processingApi.listIssues()).items.filter(
      (issue) => issue.issue_type === 'STALE_PREDECESSOR',
    );
    expect(stale.map((issue) => [issue.affected_date, issue.chain]).sort()).toEqual([
      ['2026-10-17', 'POSITIONS'],
      ['2026-10-18', 'POSITIONS'],
    ]);
  });

  it('OQ-23 a date after a fresh one with a missing price reads Atualizado com pendências', async () => {
    await finish(await enqueue('2026-10-16', '2026-10-16', 'POSITIONS'));

    expect(await status('2026-10-16')).toEqual({
      cash: 'FRESH',
      positions: 'FRESH_WITH_ISSUES',
    });
  });

  it("OQ-26 reprocessing a date replaces that chain's issues for it", async () => {
    await finish(await enqueue('2026-10-16', '2026-10-16', 'POSITIONS'));
    const second = await finish(await enqueue('2026-10-16', '2026-10-16', 'POSITIONS'));

    const missing = (await processingApi.listIssues()).items.filter(
      (issue) =>
        issue.issue_type === 'MISSING_REFERENCE_PRICE' && issue.affected_date === '2026-10-16',
    );
    expect(missing).toHaveLength(1);
    expect(missing[0]?.request_id).toBe(second.id);
  });

  it('OQ-23 a write marks stale only the dates that have a status, from its date', async () => {
    await deposit('2026-10-15');

    expect((await status('2026-10-14')).cash).toBe('FRESH');
    expect((await status('2026-10-15')).cash).toBe('STALE');
    expect((await status('2026-10-16')).cash).toBe('STALE');
    expect((await status('2026-10-17')).cash).toBe('NOT_PROCESSED');
    expect((await status('2026-10-15')).positions).toBe('FRESH');
  });

  it("OQ-26 the preview reports start−1's chain status, or the zero state per chain", async () => {
    const after = await processingApi.preview({
      start_date: '2026-10-17',
      end_date: '2026-10-17',
      scope: 'ALL',
    });
    const first = await processingApi.preview({
      start_date: '2026-10-14',
      end_date: '2026-10-14',
      scope: 'ALL',
    });
    // A deposit before any trade: cash leaves its zero state, positions do not.
    await deposit('2026-10-10');
    const afterDeposit = await processingApi.preview({
      start_date: '2026-10-12',
      end_date: '2026-10-12',
      scope: 'ALL',
    });

    expect(after.predecessor).toEqual({ cash: 'FRESH', positions: 'STALE' });
    expect(first.predecessor).toEqual({ cash: 'ZERO_STATE', positions: 'ZERO_STATE' });
    expect(afterDeposit.predecessor).toEqual({ cash: 'NOT_PROCESSED', positions: 'ZERO_STATE' });
  });

  it('§8.2 AUM has no status of its own: it is the value, null when either side is missing', async () => {
    const complete = await portfolioApi.getSummary('2026-10-15');
    const noPositions = await portfolioApi.getSummary('2026-10-17');

    expect(complete.aum).toBe('1491965.8654717340');
    expect(noPositions.aum).toBeNull();
  });

  it('OQ-23 a trade on a processed date makes both chains stale there', async () => {
    await ledgerApi.createEntry({
      type: 'TRADE',
      asset_id: IDS.di1f28,
      date: '2026-10-15',
      time: '10:00:00',
      signed_quantity: 1,
      input_kind: 'PU',
      execution_pu: '89000.00',
    });

    expect(await status('2026-10-15')).toEqual({ cash: 'STALE', positions: 'STALE' });
  });
});
