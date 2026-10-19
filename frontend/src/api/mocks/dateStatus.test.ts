import type { ProcessingRequest, ProcessingScope } from '../contract';
import { ledgerApi, portfolioApi, pricesApi, processingApi } from '../endpoints';
import { IDS } from './fixtures';

// OQ-23, OQ-26 and OQ-31 (docs/open-questions.md): a run processes its dates in calendar order
// and publishes each one in its own step; every date has one processing status per chain
// (Processado, Processado com pendências, Processando, Erro, Não processado) and a processing
// time. There is no staleness: a write never changes a status. Each date needs its day before
// processed (or the chain's zero state), or the run fails there. The fake worker advances one
// step per read of a job: it takes the oldest queued run straight to RUNNING (no dispatcher,
// OQ-46), then commits one date per read. Fixture scenario: 14–16/10 processed
// for both chains; positions on 16/10 with issues (DI1F29 has no price); 17–18/10 never.

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

/** A reference price: it changes only the positions chain's inputs from its date. */
const setPrice = (date: string) =>
  pricesApi.setReferencePrice({
    asset_id: IDS.di1f28,
    reference_date: date,
    input_kind: 'PU',
    pu: '89300.00',
  });

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

    // start (14/10 Processando), commit 14/10 (15/10 Processando)
    expect(await polls(job, 1)).toMatchObject({ status: 'RUNNING', progress_date: null });
    expect(await status('2026-10-14')).toMatchObject({ cash: 'RUNNING', positions: 'RUNNING' });
    expect(await polls(job, 1)).toMatchObject({ status: 'RUNNING', progress_date: '2026-10-14' });
    expect(await status('2026-10-14')).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED' });
    expect(await status('2026-10-15')).toMatchObject({ cash: 'RUNNING', positions: 'RUNNING' });

    expect(await finish(job)).toMatchObject({
      status: 'COMPLETED',
      progress_date: '2026-10-15',
    });
    expect(await status('2026-10-15')).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED' });
  });

  it('OQ-23 a cancel keeps the dates committed, the current one included; later dates are untouched', async () => {
    const job = await enqueue('2026-10-14', '2026-10-16', 'POSITIONS');
    await polls(job, 2); // 14/10 committed, 15/10 being processed

    await processingApi.cancel(job.id);

    expect(await finish(job)).toMatchObject({ status: 'CANCELLED', progress_date: '2026-10-15' });
    expect((await status('2026-10-15')).positions).toBe('PROCESSED');
    expect((await status('2026-10-16')).positions).toBe('PROCESSED_WITH_ISSUES');
  });

  it.each<[ProcessingScope, string, string]>([
    ['CASH', '2026-10-15', 'COMPLETED'],
    ['POSITIONS', '2026-10-16', 'COMPLETED_WITH_ISSUES'],
  ])(
    'OQ-26 a cancel during the last date lets a %s run end as it would have (%s → %s)',
    async (scope, date, ending) => {
      const job = await enqueue(date, date, scope);
      await polls(job, 1); // the only date is being processed

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
      // A single-chain run's failure names the run's chain (OQ-40 item 3).
      failed_date: '2026-10-15',
      failed_chain: 'CASH',
    });
    expect((await status('2026-10-14')).cash).toBe('PROCESSED');
    expect((await status('2026-10-15')).cash).toBe('FAILED');
    expect((await status('2026-10-16')).cash).toBe('PROCESSED');
  });

  it('OQ-23 a run ends COMPLETED_WITH_ISSUES when a date it wrote has issues', async () => {
    // 17/10 has no prices at all: its positions are processed with issues; its cash has none.
    expect((await finish(await enqueue('2026-10-17', '2026-10-17', 'POSITIONS'))).status).toBe(
      'COMPLETED_WITH_ISSUES',
    );
    expect((await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'))).status).toBe(
      'COMPLETED',
    );
  });

  it('OQ-20 there is no SUPERSEDED: a write during a run never stops it', async () => {
    const job = await enqueue('2026-10-14', '2026-10-15', 'POSITIONS');
    await polls(job, 1);

    await deposit('2026-10-14');

    expect((await finish(job)).status).toBe('COMPLETED');
  });
});

describe('OQ-23 the status of a date, per chain', () => {
  it.each<[ProcessingScope, string, string]>([
    ['POSITIONS', 'POSITIONS_PREDECESSOR_MISSING', 'POSITIONS'],
    ['CASH', 'CASH_PREDECESSOR_MISSING', 'CASH'],
    // Both chains fail on the same date: the positions code and chain (OQ-36 item 5, OQ-40 item 3).
    ['ALL', 'POSITIONS_PREDECESSOR_MISSING', 'POSITIONS'],
  ])(
    'OQ-31 OQ-40 a %s run whose day before is not processed fails on its first date (%s)',
    async (scope, code, chain) => {
      const job = await finish(await enqueue('2026-10-18', '2026-10-18', scope));

      expect(job).toMatchObject({
        status: 'FAILED',
        progress_date: null,
        error_code: code,
        error_message: 'Dia anterior não processado',
        failed_date: '2026-10-18',
        failed_chain: chain,
      });
      const after = await status('2026-10-18');
      expect(after.positions).toBe(scope === 'CASH' ? 'NOT_PROCESSED' : 'FAILED');
      expect(after.cash).toBe(scope === 'POSITIONS' ? 'NOT_PROCESSED' : 'FAILED');
      expect(
        (await processingApi.listIssues()).items.map((issue) => issue.issue_type),
      ).not.toContain('STALE_PREDECESSOR');
    },
  );

  it('OQ-36 in an ALL run one chain failing its predecessor reads Erro; the other is written on D', async () => {
    await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'));

    const job = await finish(await enqueue('2026-10-18', '2026-10-18', 'ALL'));

    expect(job).toMatchObject({
      status: 'COMPLETED_WITH_ISSUES',
      progress_date: '2026-10-18',
      error_code: 'POSITIONS_PREDECESSOR_MISSING',
      error_message: 'Dia anterior não processado',
      failed_date: '2026-10-18',
      failed_chain: 'POSITIONS',
    });
    expect(await status('2026-10-18')).toEqual({ cash: 'PROCESSED', positions: 'FAILED' });
    // AUM needs the other chain processed on the date (OQ-38).
    expect((await portfolioApi.getSummary('2026-10-18')).aum).toBeNull();
  });

  it('OQ-36 in an ALL run the surviving chain goes on to the end; the failed one is untouched after D', async () => {
    // The fake cannot recompute positions from 17/10 after a price dated then.
    await setPrice('2026-10-17');

    const job = await finish(await enqueue('2026-10-16', '2026-10-18', 'ALL'));

    expect(job).toMatchObject({
      status: 'COMPLETED_WITH_ISSUES',
      progress_date: '2026-10-18',
      error_code: 'MOCK_INPUTS_CHANGED',
      failed_date: '2026-10-17',
      failed_chain: 'POSITIONS',
    });
    expect(await status('2026-10-16')).toEqual({
      cash: 'PROCESSED',
      positions: 'PROCESSED_WITH_ISSUES',
    });
    expect(await status('2026-10-17')).toEqual({ cash: 'PROCESSED', positions: 'FAILED' });
    expect(await status('2026-10-18')).toEqual({ cash: 'PROCESSED', positions: 'NOT_PROCESSED' });
  });

  it('OQ-36 an ALL run ends FAILED only when both chains fail, keeping the first failure', async () => {
    await setPrice('2026-10-17');
    await deposit('2026-10-18');

    const job = await finish(await enqueue('2026-10-16', '2026-10-18', 'ALL'));

    expect(job).toMatchObject({
      status: 'FAILED',
      progress_date: '2026-10-17',
      error_code: 'MOCK_INPUTS_CHANGED',
      failed_date: '2026-10-17',
      failed_chain: 'POSITIONS',
    });
    expect(job.error_message).toContain('17/10/2026');
    expect(await status('2026-10-18')).toEqual({ cash: 'FAILED', positions: 'NOT_PROCESSED' });
  });

  it('OQ-36 OQ-40 both chains failing on the same date keep the positions error, even in two steps', async () => {
    // Positions have 17/10, cash does not; a price on 18/10 makes positions fail there too.
    await finish(await enqueue('2026-10-17', '2026-10-17', 'POSITIONS'));
    await setPrice('2026-10-18');

    const job = await finish(await enqueue('2026-10-18', '2026-10-18', 'ALL'));

    expect(job).toMatchObject({
      status: 'FAILED',
      error_code: 'MOCK_INPUTS_CHANGED',
      failed_date: '2026-10-18',
      failed_chain: 'POSITIONS',
    });
    expect(await status('2026-10-18')).toEqual({ cash: 'FAILED', positions: 'FAILED' });
  });

  it('OQ-36 OQ-40 an ALL run cancelled after one chain failed ends CANCELLED and keeps the failure', async () => {
    await setPrice('2026-10-16');
    const job = await enqueue('2026-10-15', '2026-10-18', 'ALL');
    await polls(job, 3); // 15/10 committed; 16/10 positions Erro, cash committed; 17/10 next

    await processingApi.cancel(job.id);

    expect(await finish(job)).toMatchObject({
      status: 'CANCELLED',
      progress_date: '2026-10-17',
      error_code: 'MOCK_INPUTS_CHANGED',
      failed_date: '2026-10-16',
      failed_chain: 'POSITIONS',
    });
  });

  it('OQ-40 a run with no failure has failed_date and failed_chain null', async () => {
    const job = await finish(await enqueue('2026-10-14', '2026-10-15', 'ALL'));

    expect(job).toMatchObject({ status: 'COMPLETED', failed_date: null, failed_chain: null });
  });

  it('OQ-31 a failed day before counts as not processed', async () => {
    // The fake cannot compute 17/10 after a deposit dated then: that date reads Erro.
    await deposit('2026-10-17');
    await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'));

    const preview = await processingApi.preview({
      start_date: '2026-10-18',
      end_date: '2026-10-18',
      scope: 'CASH',
    });
    const job = await finish(await enqueue('2026-10-18', '2026-10-18', 'CASH'));

    expect(preview.predecessor.cash).toBe('FAILED');
    expect(job.error_code).toBe('CASH_PREDECESSOR_MISSING');
  });

  it('OQ-31 a processed chain carries its own processing time', async () => {
    const before = await portfolioApi.getSummary('2026-10-15');

    await finish(await enqueue('2026-10-15', '2026-10-15', 'CASH'));
    const after = await portfolioApi.getSummary('2026-10-15');

    expect(after.cash.published_at).not.toBe(before.cash.published_at);
    expect(after.positions.published_at).toBe(before.positions.published_at);
  });

  it('OQ-23 a date after a processed one with a missing price reads Processado com pendências', async () => {
    await finish(await enqueue('2026-10-16', '2026-10-16', 'POSITIONS'));

    expect(await status('2026-10-16')).toEqual({
      cash: 'PROCESSED',
      positions: 'PROCESSED_WITH_ISSUES',
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

  it("OQ-31 a write never changes a date's status: processed figures stay until reprocessed", async () => {
    const before = await portfolioApi.getSummary('2026-10-15');

    await deposit('2026-10-15');

    expect(await portfolioApi.getSummary('2026-10-15')).toEqual(before);
    expect((await status('2026-10-16')).cash).toBe('PROCESSED');
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

    expect(after.predecessor).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED_WITH_ISSUES' });
    expect(first.predecessor).toEqual({ cash: 'ZERO_STATE', positions: 'ZERO_STATE' });
    expect(afterDeposit.predecessor).toEqual({ cash: 'NOT_PROCESSED', positions: 'ZERO_STATE' });
  });

  it.each<ProcessingScope>(['CASH', 'POSITIONS', 'ALL'])(
    'OQ-39 a %s preview returns both chains',
    async (scope) => {
      await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'));

      const preview = await processingApi.preview({
        start_date: '2026-10-18',
        end_date: '2026-10-18',
        scope,
      });

      expect(preview.predecessor).toEqual({ cash: 'PROCESSED', positions: 'NOT_PROCESSED' });
    },
  );

  it('§8.2 AUM has no status of its own: it is the value, null when either side is missing', async () => {
    const complete = await portfolioApi.getSummary('2026-10-15');
    const noPositions = await portfolioApi.getSummary('2026-10-17');

    expect(complete.aum).toBe('1491965.8654717340');
    expect(noPositions.aum).toBeNull();
  });

  it('OQ-38 a chain written while the other is processed keeps AUM = cash + market value', async () => {
    await finish(await enqueue('2026-10-15', '2026-10-15', 'CASH'));

    expect((await portfolioApi.getSummary('2026-10-15')).aum).toBe('1491965.8654717340');
  });

  it('OQ-38 OQ-40 a chain written while the other is Erro on that date leaves AUM null', async () => {
    // The fake cannot recompute 15/10's cash after a deposit dated then: cash reads Erro.
    await deposit('2026-10-15');
    await finish(await enqueue('2026-10-15', '2026-10-15', 'CASH'));
    expect((await portfolioApi.getSummary('2026-10-15')).aum).toBe('1491965.8654717340');

    await finish(await enqueue('2026-10-15', '2026-10-15', 'POSITIONS'));

    const summary = await portfolioApi.getSummary('2026-10-15');
    expect(summary.cash.status).toBe('FAILED');
    expect(summary.positions.status).toBe('PROCESSED');
    expect(summary.cash.balance).not.toBeNull();
    expect(summary.positions.market_value).not.toBeNull();
    expect(summary.aum).toBeNull();
  });

  it('OQ-38 a chain written while the other is not processed leaves AUM null', async () => {
    await finish(await enqueue('2026-10-17', '2026-10-17', 'CASH'));

    const summary = await portfolioApi.getSummary('2026-10-17');
    expect(summary.cash.balance).not.toBeNull();
    expect(summary.aum).toBeNull();
  });

  it('OQ-40 the zero state needs no earlier status for the chain: a gap after one fails the date', async () => {
    // Nothing is dated before 14/10, so 01/10 is processed from the zero state.
    expect((await finish(await enqueue('2026-10-01', '2026-10-01', 'CASH'))).status).toBe(
      'COMPLETED',
    );

    const preview = await processingApi.preview({
      start_date: '2026-10-05',
      end_date: '2026-10-05',
      scope: 'ALL',
    });
    const job = await finish(await enqueue('2026-10-05', '2026-10-05', 'CASH'));

    // Cash has a status on 01/10, so 04/10 unprocessed is a gap; positions have none.
    expect(preview.predecessor).toEqual({ cash: 'NOT_PROCESSED', positions: 'ZERO_STATE' });
    expect(job).toMatchObject({ status: 'FAILED', error_code: 'CASH_PREDECESSOR_MISSING' });
  });

  it('OQ-31 a trade on a processed date leaves both chains as they were', async () => {
    await ledgerApi.createEntry({
      type: 'TRADE',
      asset_id: IDS.di1f28,
      date: '2026-10-15',
      time: '10:00:00',
      signed_quantity: 1,
      input_kind: 'PU',
      execution_pu: '89000.00',
    });

    expect(await status('2026-10-15')).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED' });
  });
});
