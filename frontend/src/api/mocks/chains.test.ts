import type { ProcessingRequest, ProcessingScope } from '../contract';
import { ledgerApi, portfolioApi, pricesApi, processingApi } from '../endpoints';
import { ApiError } from '../http';
import { db } from './db';
import { IDS } from './fixtures';

// OQ-21 (recorded): cash and positions are two separately processed
// chains that read the same ledger facts and meet only in AUM. Every processing request has a
// scope (CASH, POSITIONS or ALL); a write changes no status (OQ-31). Expected values come
// from the fixture scenario (src/api/mocks/fixtures.ts): 14–16/10 published for both chains,
// positions on 16/10 with issues, the 16/10 price corrected after publication.

const FINAL = ['COMPLETED', 'COMPLETED_WITH_ISSUES', 'CANCELLED', 'FAILED'];

async function run(start: string, end: string, scope: ProcessingScope): Promise<ProcessingRequest> {
  const job = await processingApi.enqueue({ start_date: start, end_date: end, scope });
  for (let i = 0; i < 50; i += 1) {
    const current = await processingApi.getRequest(job.id);
    if (FINAL.includes(current.status)) return current;
  }
  throw new Error('the job never finished');
}

const deposit = (date: string) =>
  ledgerApi.createEntry({
    type: 'CASH',
    date: date,
    time: '12:00:00',
    cash_amount: '1000.00',
  });

const trade = (date: string) =>
  ledgerApi.createEntry({
    type: 'TRADE',
    asset_id: IDS.di1f28,
    date: date,
    time: '10:00:00',
    signed_quantity: 1,
    input_kind: 'PU',
    execution_pu: '89000.00',
  });

describe('OQ-21 the summary keeps cash, positions and AUM apart', () => {
  it('§8.2 a fully published day: cash and positions processed, AUM with its value', async () => {
    const summary = await portfolioApi.getSummary('2026-10-15');

    expect(summary).toMatchObject({
      date: '2026-10-15',
      cash: { status: 'PROCESSED', balance: '199650.3745326500' },
      positions: {
        status: 'PROCESSED',
        market_value: '1292315.4909390840',
        valuation_status: 'COMPLETE',
        position_pnl: '1220.1988777680',
        trades_pnl: '-9254.3334060340',
        daily_pnl: '-8034.1345282660',
        cumulative_pnl: '-8034.1345282660',
        pnl_status: 'COMPLETE',
      },
      aum: '1491965.8654717340',
    });
  });

  it('OQ-31 a price corrected after processing changes no status', async () => {
    const summary = await portfolioApi.getSummary('2026-10-16');

    expect(summary.cash).toMatchObject({ status: 'PROCESSED', balance: '506059.2651460232' });
    // DI1F29 has no price on 16/10: processed with issues, as it was processed.
    expect(summary.positions.status).toBe('PROCESSED_WITH_ISSUES');
    expect(summary.aum).toBeNull();
  });

  it('§12 D3 a day never processed: both chains unprocessed, every figure null, AUM included', async () => {
    const summary = await portfolioApi.getSummary('2026-10-17');

    expect(summary.cash).toMatchObject({
      status: 'NOT_PROCESSED',
      balance: null,
      published_at: null,
    });
    expect(summary.positions).toMatchObject({ status: 'NOT_PROCESSED', market_value: null });
    expect(summary.aum).toBeNull();
  });
});

describe('OQ-21 the cash of a day carries its components (user, 2026-10-18)', () => {
  it.each([
    ['2026-10-14', '-890064.6254673500', '1500000.00', '0.00', '609935.3745326500'],
    ['2026-10-15', '-410285.00', '0.00', '0.00', '199650.3745326500'],
    ['2026-10-16', '356408.8906133732', '0.00', '50000.00', '506059.2651460232'],
  ])(
    '§7 %s: trades cash flow, deposits and withdrawals next to the balance',
    async (date, flow, deposits, withdrawals, balance) => {
      expect((await portfolioApi.getSummary(date)).cash).toMatchObject({
        balance,
        trades_cash_flow: flow,
        deposits,
        withdrawals,
      });
    },
  );

  it('§12 D3 a day never processed has no components either', async () => {
    expect((await portfolioApi.getSummary('2026-10-17')).cash).toMatchObject({
      trades_cash_flow: null,
      deposits: null,
      withdrawals: null,
    });
  });

  it('§10.4 a CASH job publishes the components of its days', async () => {
    await run('2026-10-17', '2026-10-17', 'CASH');

    expect((await portfolioApi.getSummary('2026-10-17')).cash).toMatchObject({
      balance: '506059.2651460232',
      trades_cash_flow: '0.0000000000',
      deposits: '0.00',
      withdrawals: '0.00',
    });
  });
});

describe("OQ-31 no write changes a date's status", () => {
  it('§6.1 §6.2 §5 a deposit, a trade and a price leave every status as it was', async () => {
    const before = await portfolioApi.getSummary('2026-10-15');

    await deposit('2026-10-15');
    await trade('2026-10-15');
    await pricesApi.setReferencePrice({
      asset_id: IDS.di1f28,
      reference_date: '2026-10-15',
      input_kind: 'PU',
      pu: '89130.00',
    });

    const after = await portfolioApi.getSummary('2026-10-15');
    expect(after.cash.status).toBe(before.cash.status);
    expect(after.positions.status).toBe(before.positions.status);
  });
});

describe('OQ-21 a job publishes only its scope', () => {
  it('§10.4 CASH publishes the cash of its days and leaves positions unprocessed', async () => {
    expect((await run('2026-10-17', '2026-10-18', 'CASH')).status).toBe('COMPLETED');

    const summary = await portfolioApi.getSummary('2026-10-18');
    expect(summary.cash).toMatchObject({ status: 'PROCESSED', balance: '506059.2651460232' });
    expect(summary.positions.status).toBe('NOT_PROCESSED');
    expect(summary.aum).toBeNull();
    expect((await portfolioApi.getPositions('2026-10-18')).status).toBe('NOT_PROCESSED');
  });

  it('§10.4 POSITIONS republishes positions, now current with a missing price; cash is untouched', async () => {
    const cashBefore = (await portfolioApi.getSummary('2026-10-16')).cash;

    expect((await run('2026-10-16', '2026-10-16', 'POSITIONS')).status).toBe(
      'COMPLETED_WITH_ISSUES',
    );

    const summary = await portfolioApi.getSummary('2026-10-16');
    // OQ-23: 15/10 is current and DI1F29 has no price on 16/10: Processado com pendências.
    expect(summary.positions).toMatchObject({
      status: 'PROCESSED_WITH_ISSUES',
      trades_pnl: '-592.3681943852',
    });
    expect(summary.cash).toEqual(cashBefore);
  });

  it('§10.4 ALL publishes both chains', async () => {
    await run('2026-10-16', '2026-10-18', 'ALL');

    // 17/10 and 18/10 have no prices at all (OQ-23: Processado com pendências for positions).
    const summary = await portfolioApi.getSummary('2026-10-18');
    expect(summary.cash.status).toBe('PROCESSED');
    expect(summary.positions.status).toBe('PROCESSED_WITH_ISSUES');
    expect(summary.aum).toBeNull();
  });

  it('OQ-23 a CASH run writes only the cash status: positions stay as they were', async () => {
    await run('2026-10-16', '2026-10-18', 'CASH');

    const summary = await portfolioApi.getSummary('2026-10-16');
    expect(summary.cash.status).toBe('PROCESSED');
    expect(summary.positions.status).toBe('PROCESSED_WITH_ISSUES');
  });

  it('§10.4 a deposit does not stop a POSITIONS job; it fails a CASH job (fake backend)', async () => {
    await deposit('2026-10-16');

    expect((await run('2026-10-16', '2026-10-16', 'POSITIONS')).status).toBe(
      'COMPLETED_WITH_ISSUES',
    );
    expect((await run('2026-10-16', '2026-10-16', 'CASH')).status).toBe('FAILED');
  });

  it.each([
    ['a trade', () => trade('2026-10-18'), 'COMPLETED'],
    [
      'a price',
      () =>
        pricesApi.setReferencePrice({
          asset_id: IDS.di1f28,
          reference_date: '2026-10-15',
          input_kind: 'PU',
          pu: '89130.00',
        }),
      'COMPLETED',
    ],
  ])(
    'OQ-23 %s dated after its range never stops a CASH run (%s)',
    async (_write, write, status) => {
      const job = await processingApi.enqueue({
        start_date: '2026-10-14',
        end_date: '2026-10-15',
        scope: 'CASH',
      });
      await processingApi.getRequest(job.id); // DISPATCHED
      await processingApi.getRequest(job.id); // RUNNING
      await write();

      let current = job;
      for (let i = 0; i < 10 && !FINAL.includes(current.status); i += 1) {
        current = await processingApi.getRequest(job.id);
      }
      expect(current.status).toBe(status);
    },
  );

  it('§10.3 an expired open position does not concern a CASH job', async () => {
    db.issues.push({
      id: 'expired',
      issue_type: 'EXPIRED_OPEN_POSITION',
      asset_id: IDS.di1f27,
      asset_code: 'DI1F27',
      affected_date: '2026-10-15',
      required_price_date: null,
      request_id: 'seed',
    });

    expect((await run('2026-10-14', '2026-10-15', 'CASH')).status).toBe('COMPLETED');
  });

  it('OQ-23 a cash write during a POSITIONS run does not stop it', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      scope: 'POSITIONS',
    });
    await processingApi.getRequest(job.id); // DISPATCHED
    await processingApi.getRequest(job.id); // RUNNING
    await deposit('2026-10-18');

    let current = job;
    for (let i = 0; i < 10 && !FINAL.includes(current.status); i += 1) {
      current = await processingApi.getRequest(job.id);
    }
    expect(current.status).toBe('COMPLETED');
  });
});

describe('OQ-21 scope on requests, preview and Pendências', () => {
  it('§10.1 echoes the scope on the job and requires one', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-14',
      scope: 'CASH',
    });
    expect(job.scope).toBe('CASH');

    const problem = await processingApi
      .enqueue({ start_date: '2026-10-14', end_date: '2026-10-14' } as never)
      .then(
        () => null,
        (error: unknown) => (error instanceof ApiError ? error.problem : null),
      );
    expect(problem?.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'scope' });
  });

  it('OQ-11 the preview reports the state before the range for each chain', async () => {
    const preview = await processingApi.preview({
      start_date: '2026-10-17',
      end_date: '2026-10-18',
      scope: 'ALL',
    });

    expect(preview).toMatchObject({
      scope: 'ALL',
      predecessor_date: '2026-10-16',
      predecessor: { cash: 'PROCESSED', positions: 'PROCESSED_WITH_ISSUES' },
    });
  });

  it('OQ-31 a CASH run after a day with no processed cash fails on its first date', async () => {
    const job = await run('2026-10-18', '2026-10-18', 'CASH');

    expect(job).toMatchObject({
      status: 'FAILED',
      error_code: 'CASH_PREDECESSOR_MISSING',
      error_message: 'Dia anterior não processado',
    });
    // That date reads Erro for cash; positions are untouched; no Pendência is raised.
    const summary = await portfolioApi.getSummary('2026-10-18');
    expect(summary.cash.status).toBe('FAILED');
    expect(summary.positions.status).toBe('NOT_PROCESSED');
    expect((await processingApi.listIssues()).items).toHaveLength(1);
  });

  it('OQ-31 queuing it is still allowed, and the preview reports the missing cash', async () => {
    const preview = await processingApi.preview({
      start_date: '2026-10-18',
      end_date: '2026-10-18',
      scope: 'CASH',
    });
    expect(preview.predecessor.cash).toBe('NOT_PROCESSED');
    expect(
      (
        await processingApi.enqueue({
          start_date: '2026-10-18',
          end_date: '2026-10-18',
          scope: 'CASH',
        })
      ).status,
    ).toBe('QUEUED');
  });
});
