import type { PortfolioPositions, PortfolioSummary, ProcessingRequest } from '../contract';
import { assetsApi, ledgerApi, portfolioApi, pricesApi, processingApi } from '../endpoints';
import { ApiError } from '../http';
import { IDS } from './fixtures';

// The MSW fake backend must honour the documented rules, so screens built against it behave
// like they will against the real API. Expected values come from the spec and the fixtures'
// documented scenario (src/api/mocks/fixtures.ts).

async function problemOf(promise: Promise<unknown>) {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error.problem;
    throw error;
  }
  throw new Error('expected an error');
}

function published<T extends PortfolioSummary | PortfolioPositions>(
  value: T,
): Extract<T, { publication: 'PUBLISHED' }> {
  if (value.publication !== 'PUBLISHED') throw new Error('expected a published date');
  return value as Extract<T, { publication: 'PUBLISHED' }>;
}

describe('mock portfolio', () => {
  it('§8.2 §11.4 returns the published summary of a complete day', async () => {
    const summary = published(await portfolioApi.getSummary('2026-10-15'));

    expect(summary).toMatchObject({
      stale: false,
      cash_balance: '199650.3745326500',
      positions_market_value: '1292315.4909390840',
      aum: '1491965.8654717340',
      position_pnl: '1220.1988777680',
      trades_pnl: '-9254.3334060340',
      daily_pnl: '-8034.1345282660',
      valuation_status: 'COMPLETE',
      pnl_status: 'COMPLETE',
    });
  });

  it('§8.3 keeps cash but returns null valuation and P&L when a price is missing', async () => {
    const summary = published(await portfolioApi.getSummary('2026-10-16'));

    expect(summary).toMatchObject({
      cash_balance: '506059.2651460232',
      aum: null,
      daily_pnl: null,
      cumulative_pnl: null,
      valuation_status: 'MISSING',
      pnl_status: 'MISSING',
    });
  });

  it('§8.3 shows the asset without a price with quantity and averages but null figures', async () => {
    const positions = published(await portfolioApi.getPositions('2026-10-16'));
    const di1f29 = positions.items.find((row) => row.asset_code === 'DI1F29');

    expect(di1f29).toMatchObject({
      quantity: 5,
      average_entry_pu: '82057.00',
      reference_pu: null,
      financial_total: null,
      position_pnl: null,
      daily_pnl: null,
      valuation_status: 'MISSING',
    });
  });

  it('§10.4 flags a date as stale when its price was corrected after publication', async () => {
    expect(published(await portfolioApi.getSummary('2026-10-16')).stale).toBe(true);
  });

  it('§12 D3 reports a date that was never processed instead of inventing figures', async () => {
    expect(await portfolioApi.getSummary('2026-10-17')).toEqual({
      date: '2026-10-17',
      publication: 'NOT_PROCESSED',
    });
  });

  it('OQ-16 returns the cumulative series with the gap as null', async () => {
    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-01',
      end_date: '2026-10-18',
    });

    expect(items.map((p) => [p.date, p.cumulative_pnl])).toEqual([
      ['2026-10-14', '0.0000000000'],
      ['2026-10-15', '-8034.1345282660'],
      ['2026-10-16', null],
    ]);
  });
});

describe('mock reference prices', () => {
  it('§5 prefers MANUAL over B3 and lists only dates with an observation', async () => {
    const { items } = await pricesApi.listReferencePrices({
      asset_id: IDS.di1f28,
      start_date: '2026-10-14',
      end_date: '2026-10-18',
    });

    expect(items.map((d) => d.reference_date)).toEqual(['2026-10-16', '2026-10-15', '2026-10-14']);
    expect(items[0]?.preferred).toMatchObject({ source: 'MANUAL', revision: 2, rate: '0.0980' });
    expect(items[0]?.current.map((p) => p.source).sort()).toEqual(['B3', 'MANUAL']);
  });

  it('§5 keeps every revision for "Ver revisões"', async () => {
    const { items } = await pricesApi.listRevisions({
      asset_id: IDS.di1f28,
      reference_date: '2026-10-16',
    });

    expect(items.map((p) => [p.source, p.revision, p.superseded_at === null])).toEqual([
      ['MANUAL', 2, true],
      ['B3', 1, true],
      ['MANUAL', 1, false],
    ]);
  });

  it('§5 a correction appends a revision, supersedes the previous one and marks the date stale', async () => {
    const created = await pricesApi.setReferencePrice({
      asset_id: IDS.di1f28,
      reference_date: '2026-10-16',
      input_kind: 'PU',
      pu: '89260.00',
    });
    const { items } = await pricesApi.listRevisions({
      asset_id: IDS.di1f28,
      reference_date: '2026-10-16',
    });
    const manual = items.filter((p) => p.source === 'MANUAL');

    expect(created).toMatchObject({ source: 'MANUAL', revision: 3, pu: '89260.00' });
    expect(manual.map((p) => [p.revision, p.superseded_at === null])).toEqual([
      [3, true],
      [2, false],
      [1, false],
    ]);
    expect(published(await portfolioApi.getSummary('2026-10-16')).stale).toBe(true);
  });

  it('§5 requires the contract when listing reference prices', async () => {
    const problem = await problemOf(
      pricesApi.listReferencePrices({
        asset_id: '',
        start_date: '2026-10-01',
        end_date: '2026-10-18',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'asset_id' });
  });

  it('OQ-19 shows each contract latest observation with its date', async () => {
    const { items } = await assetsApi.listInstruments({ product_id: IDS.di1 });

    expect(items.map((i) => [i.code, i.last_reference?.reference_date ?? null])).toEqual([
      ['DI1F27', null],
      ['DI1F28', '2026-10-16'],
      ['DI1F29', '2026-10-15'],
      ['DI1F30', null],
    ]);
  });
});

describe('mock ledger validation', () => {
  const trade = {
    asset_id: IDS.di1f28,
    trade_date: '2026-10-17',
    trade_time: '10:00:00',
    signed_quantity: 1,
    input_kind: 'PU' as const,
    execution_pu: '89000.00',
  };

  it('OQ-14 rejects a date after today with FUTURE_DATE on the field', async () => {
    const problem = await problemOf(ledgerApi.createTrade({ ...trade, trade_date: '2026-10-19' }));

    expect(problem.status).toBe(422);
    expect(problem.errors).toEqual([
      {
        code: 'FUTURE_DATE',
        message: 'A data não pode ser posterior a hoje.',
        field: 'trade_date',
      },
    ]);
  });

  it('OQ-3 rejects a PU with more than 10 decimals instead of rounding it', async () => {
    const problem = await problemOf(
      ledgerApi.createTrade({ ...trade, execution_pu: '89000.12345678901' }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'execution_pu' });
  });

  it('OQ-3 rejects a typed rate with more than 12 decimals', async () => {
    const problem = await problemOf(
      ledgerApi.createTrade({
        ...trade,
        input_kind: 'RATE',
        execution_rate: '0.1234567890123',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({
      code: 'VALIDATION_ERROR',
      field: 'execution_rate',
    });
  });

  it('OQ-1 rejects a trade dated after the maturity with CONTRACT_MATURED', async () => {
    const matured = await assetsApi.createInstrument({
      product_id: IDS.di1,
      code: 'DI1V26',
      maturity_date: '2026-10-01',
    });

    const problem = await problemOf(ledgerApi.createTrade({ ...trade, asset_id: matured.id }));

    expect(problem.errors?.[0]).toMatchObject({ code: 'CONTRACT_MATURED', field: 'trade_date' });
  });

  it('OQ-1 on the maturity date takes the PU and stores the rate as 0', async () => {
    const maturing = await assetsApi.createInstrument({
      product_id: IDS.di1,
      code: 'DI1X26',
      maturity_date: '2026-10-17',
    });

    const byRate = await problemOf(
      ledgerApi.createTrade({
        ...trade,
        asset_id: maturing.id,
        input_kind: 'RATE',
        execution_rate: '0.10',
      }),
    );
    const byPu = await ledgerApi.createTrade({
      ...trade,
      asset_id: maturing.id,
      execution_pu: '100000',
    });

    expect(byRate.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'execution_rate' });
    expect(byPu).toMatchObject({ execution_pu: '100000', execution_rate: '0' });
  });

  it('OQ-3 rejects a cash amount with more than 2 decimals', async () => {
    const problem = await problemOf(
      ledgerApi.createCashMovement({
        movement_date: '2026-10-17',
        movement_type: 'DEPOSIT',
        amount: '10.001',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'amount' });
  });

  it('§10.1 a new trade only marks results stale; it never starts a job', async () => {
    const before = (await processingApi.listRequests()).items.length;

    await ledgerApi.createTrade({ ...trade, trade_date: '2026-10-15' });

    expect(published(await portfolioApi.getSummary('2026-10-15')).stale).toBe(true);
    expect((await processingApi.listRequests()).items).toHaveLength(before);
  });

  it('§6.1 deletes several entries atomically: one unknown id deletes nothing', async () => {
    const range = { start_date: '2026-10-01', end_date: '2026-10-18' };
    const [first] = (await ledgerApi.listTrades(range)).items;

    const problem = await problemOf(
      ledgerApi.deleteEntries({ trade_ids: [first?.id ?? '', 'missing'], cash_movement_ids: [] }),
    );

    expect(problem.status).toBe(404);
    expect((await ledgerApi.listTrades(range)).items).toHaveLength(3);
  });
});

describe('mock processing', () => {
  async function poll(id: string): Promise<ProcessingRequest> {
    return processingApi.getRequest(id);
  }

  it('§10.2 runs one queued job day by day to completion', async () => {
    const job = await processingApi.enqueue({ start_date: '2026-10-14', end_date: '2026-10-15' });
    expect(job).toMatchObject({ status: 'QUEUED', total_days: 2, processed_days: 0 });

    expect((await poll(job.id)).status).toBe('DISPATCHED');
    expect(await poll(job.id)).toMatchObject({ status: 'RUNNING', progress_date: '2026-10-14' });
    expect(await poll(job.id)).toMatchObject({ processed_days: 1, progress_date: '2026-10-15' });
    expect(await poll(job.id)).toMatchObject({ status: 'COMPLETED', processed_days: 2 });
  });

  it('§10.3 ends with COMPLETED_WITH_ISSUES when the range has a missing price', async () => {
    const job = await processingApi.enqueue({ start_date: '2026-10-16', end_date: '2026-10-16' });
    for (let i = 0; i < 3; i += 1) await poll(job.id);

    expect((await poll(job.id)).status).toBe('COMPLETED_WITH_ISSUES');
  });

  it('§10.2 cancels a queued job at once and a running one cooperatively', async () => {
    const queued = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-16',
    });
    const second = await processingApi.enqueue({
      start_date: '2026-10-15',
      end_date: '2026-10-16',
    });
    await poll(queued.id); // DISPATCHED
    await poll(queued.id); // RUNNING

    expect((await processingApi.cancel(second.id)).status).toBe('CANCELLED');
    expect((await processingApi.cancel(queued.id)).status).toBe('CANCELLING');
    expect((await poll(queued.id)).status).toBe('CANCELLED');
  });

  it('§10.2 runs one job at a time: the next stays queued until the active one ends', async () => {
    const first = await processingApi.enqueue({ start_date: '2026-10-14', end_date: '2026-10-15' });
    const second = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-14',
    });

    await poll(first.id); // first DISPATCHED
    expect((await poll(second.id)).status).toBe('QUEUED'); // first RUNNING
    expect((await poll(second.id)).status).toBe('QUEUED'); // first day 2
    expect((await poll(first.id)).status).toBe('COMPLETED');
    expect((await poll(second.id)).status).toBe('DISPATCHED');
  });

  it('§10.2 marks a job SUPERSEDED when an input changes during the run', async () => {
    const job = await processingApi.enqueue({ start_date: '2026-10-14', end_date: '2026-10-15' });
    await poll(job.id); // DISPATCHED
    await poll(job.id); // RUNNING

    await ledgerApi.createCashMovement({
      movement_date: '2026-10-15',
      movement_type: 'DEPOSIT',
      amount: '1000.00',
    });
    await poll(job.id);

    expect((await poll(job.id)).status).toBe('SUPERSEDED');
    expect(published(await portfolioApi.getSummary('2026-10-15')).stale).toBe(true);
  });

  it('OQ-11 runs a range whose predecessor is stale and raises STALE_PREDECESSOR', async () => {
    const job = await processingApi.enqueue({ start_date: '2026-10-17', end_date: '2026-10-17' });
    for (let i = 0; i < 3; i += 1) await poll(job.id);

    expect((await poll(job.id)).status).toBe('COMPLETED_WITH_ISSUES');
    expect((await processingApi.listIssues()).items).toContainEqual(
      expect.objectContaining({ issue_type: 'STALE_PREDECESSOR', affected_date: '2026-10-17' }),
    );
  });

  it('§10.2 refuses to cancel a finished job with JOB_NOT_CANCELLABLE', async () => {
    const { items } = await processingApi.listRequests();
    const finished = items.find((r) => r.status === 'COMPLETED');

    const problem = await problemOf(processingApi.cancel(finished?.id ?? ''));

    expect(problem.status).toBe(409);
    expect(problem.errors?.[0]?.code).toBe('JOB_NOT_CANCELLABLE');
  });

  it('§10.2 cancel and replace cancels the active job and queues the new range', async () => {
    const active = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-16',
    });

    const result = await processingApi.cancelAndReplace(active.id, {
      start_date: '2026-10-14',
      end_date: '2026-10-18',
    });

    expect(result.cancelled.status).toBe('CANCELLED');
    expect(result.replacement).toMatchObject({ status: 'QUEUED', total_days: 5 });
  });

  it.each([
    ['2026-10-14', 'ZERO_STATE'],
    ['2026-10-16', 'VALID'],
    ['2026-10-17', 'STALE'],
    ['2026-10-18', 'NOT_PROCESSED'],
  ])('OQ-11 previews a range starting %s with predecessor %s', async (start, state) => {
    const preview = await processingApi.preview({ start_date: start, end_date: '2026-10-18' });

    expect(preview.predecessor_state).toBe(state);
  });

  it('OQ-11 rejects a range that starts after it ends', async () => {
    const problem = await problemOf(
      processingApi.preview({ start_date: '2026-10-16', end_date: '2026-10-15' }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'INVALID_RANGE', field: 'start_date' });
  });

  it('§10.3 lists the missing price as the only Pendência', async () => {
    const { items } = await processingApi.listIssues();

    expect(items).toEqual([
      expect.objectContaining({
        issue_type: 'MISSING_REFERENCE_PRICE',
        asset_code: 'DI1F29',
        required_price_date: '2026-10-16',
      }),
    ]);
  });
});
