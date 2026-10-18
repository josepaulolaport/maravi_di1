import type { PortfolioPositions, PortfolioSummary, ProcessingRequest } from '../contract';
import { assetsApi, ledgerApi, portfolioApi, pricesApi, processingApi } from '../endpoints';
import { ApiError } from '../http';
import { IDS, PRICE_IDS } from './fixtures';

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

describe('mock assets', () => {
  it('§4.1 the futures spec carries no pricing methodology: DC/365 is the only convention', async () => {
    const product = await assetsApi.getProduct(IDS.di1);

    expect(product.futures).toEqual({
      face_value: '100000',
      contract_multiplier: '1',
      settlement_method: 'CASH',
      settlement_description: 'Liquidação financeira',
    });
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

describe('mock publication (a finished job publishes the precomputed results of its days)', () => {
  const FINAL = ['COMPLETED', 'COMPLETED_WITH_ISSUES', 'CANCELLED', 'FAILED', 'SUPERSEDED'];

  /** Queues [start, end] and polls it until it reaches a final status. */
  async function run(start: string, end: string): Promise<ProcessingRequest> {
    const job = await processingApi.enqueue({ start_date: start, end_date: end });
    for (let i = 0; i < 50; i += 1) {
      const current = await processingApi.getRequest(job.id);
      if (FINAL.includes(current.status)) return current;
    }
    throw new Error('the job never finished');
  }

  async function missingPrices(): Promise<string[]> {
    const { items } = await processingApi.listIssues();
    return items
      .filter((i) => i.issue_type === 'MISSING_REFERENCE_PRICE')
      .map((i) => `${i.asset_code ?? ''} ${i.required_price_date ?? ''}`)
      .sort();
  }

  it('§10.4 OQ-12 republishes 16/10 with the corrected price and clears its stale flag', async () => {
    expect((await run('2026-10-16', '2026-10-18')).status).toBe('COMPLETED_WITH_ISSUES');

    const summary = published(await portfolioApi.getSummary('2026-10-16'));
    expect(summary).toMatchObject({
      stale: false,
      cash_balance: '506059.2651460232',
      positions_market_value: null,
      aum: null,
      position_pnl: null,
      trades_pnl: '-592.3681943852',
      daily_pnl: null,
      cumulative_pnl: null,
      valuation_status: 'MISSING',
      pnl_status: 'MISSING',
    });
    expect(summary.published_at).not.toBe('2026-10-16T18:40:00-03:00');

    const rows = published(await portfolioApi.getPositions('2026-10-16')).items;
    expect(rows.find((r) => r.asset_code === 'DI1F28')).toMatchObject({
      quantity: 6,
      average_entry_pu: '89006.4625467350',
      average_entry_rate: '0.10',
      reference_price_id: PRICE_IDS.f28_1016_r2,
      reference_source: 'MANUAL',
      reference_pu: '89250.3147019396',
      reference_rate: '0.0980',
      financial_total: '535501.8882116376',
      position_pnl: '1218.3226742780',
      trades_pnl: '-592.3681943852',
      daily_pnl: '625.9544798928',
      valuation_status: 'COMPLETE',
      pnl_status: 'COMPLETE',
    });
    expect(rows.find((r) => r.asset_code === 'DI1F29')).toMatchObject({
      quantity: 5,
      reference_pu: null,
      financial_total: null,
      position_pnl: null,
      trades_pnl: '0',
      daily_pnl: null,
      valuation_status: 'MISSING',
    });
  });

  it.each(['2026-10-17', '2026-10-18'])(
    '§5 §8.3 publishes %s with quantities and cash but no valuation: no carry-forward',
    async (date) => {
      await run('2026-10-16', '2026-10-18');

      expect(published(await portfolioApi.getSummary(date))).toMatchObject({
        stale: false,
        cash_balance: '506059.2651460232',
        positions_market_value: null,
        aum: null,
        position_pnl: null,
        trades_pnl: '0',
        daily_pnl: null,
        cumulative_pnl: null,
        valuation_status: 'MISSING',
        pnl_status: 'MISSING',
      });
      const rows = published(await portfolioApi.getPositions(date)).items;
      expect(rows.map((r) => [r.asset_code, r.quantity, r.reference_pu, r.trades_pnl])).toEqual([
        ['DI1F28', 6, null, '0'],
        ['DI1F29', 5, null, '0'],
      ]);
    },
  );

  it('§10.3 replaces the range Pendências with one missing price per contract and day', async () => {
    await run('2026-10-16', '2026-10-18');

    expect(await missingPrices()).toEqual([
      'DI1F28 2026-10-17',
      'DI1F28 2026-10-18',
      'DI1F29 2026-10-16',
      'DI1F29 2026-10-17',
      'DI1F29 2026-10-18',
    ]);
  });

  it('OQ-16 extends the P&L series with the published days, unavailable from the gap', async () => {
    await run('2026-10-16', '2026-10-18');

    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-14',
      end_date: '2026-10-18',
    });
    expect(items.map((p) => [p.date, p.cumulative_pnl, p.stale])).toEqual([
      ['2026-10-14', '0.0000000000', false],
      ['2026-10-15', '-8034.1345282660', false],
      ['2026-10-16', null, false],
      ['2026-10-17', null, false],
      ['2026-10-18', null, false],
    ]);
  });

  it('OQ-12 keeps a marker before the range: 17–18/10 publish but read as stale', async () => {
    expect((await run('2026-10-17', '2026-10-18')).status).toBe('COMPLETED_WITH_ISSUES');

    for (const date of ['2026-10-16', '2026-10-17', '2026-10-18']) {
      expect(published(await portfolioApi.getSummary(date)).stale).toBe(true);
    }
  });

  it('OQ-11 a range after an unprocessed day reads as stale until the gap is processed', async () => {
    await run('2026-10-16', '2026-10-16');
    expect(
      (await processingApi.preview({ start_date: '2026-10-17', end_date: '2026-10-17' }))
        .predecessor_state,
    ).toBe('VALID');

    await run('2026-10-18', '2026-10-18');
    expect(published(await portfolioApi.getSummary('2026-10-18')).stale).toBe(true);
    expect((await processingApi.listIssues()).items).toContainEqual(
      expect.objectContaining({ issue_type: 'STALE_PREDECESSOR', affected_date: '2026-10-18' }),
    );

    await run('2026-10-17', '2026-10-18');
    expect(published(await portfolioApi.getSummary('2026-10-18')).stale).toBe(false);
    expect((await processingApi.listIssues()).items).not.toContainEqual(
      expect.objectContaining({ issue_type: 'STALE_PREDECESSOR' }),
    );
  });

  it('§7 publishes the days before the first entry as the zero state', async () => {
    expect((await run('2026-10-10', '2026-10-13')).status).toBe('COMPLETED');

    expect(published(await portfolioApi.getSummary('2026-10-12'))).toMatchObject({
      stale: false,
      cash_balance: '0',
      positions_market_value: '0',
      aum: '0',
      position_pnl: '0',
      trades_pnl: '0',
      daily_pnl: '0',
      cumulative_pnl: '0',
      valuation_status: 'COMPLETE',
      pnl_status: 'COMPLETE',
    });
    expect(published(await portfolioApi.getPositions('2026-10-12')).items).toEqual([]);
  });

  it('§10.4 a range before the first changed day still publishes', async () => {
    await ledgerApi.createCashMovement({
      movement_date: '2026-10-17',
      movement_type: 'DEPOSIT',
      amount: '1000.00',
    });

    expect((await run('2026-10-14', '2026-10-16')).status).toBe('COMPLETED_WITH_ISSUES');
    const summary = published(await portfolioApi.getSummary('2026-10-16'));
    expect(summary).toMatchObject({ stale: false, trades_pnl: '-592.3681943852' });
    const rows = published(await portfolioApi.getPositions('2026-10-16')).items;
    expect(rows.find((r) => r.asset_code === 'DI1F28')?.reference_price_id).toBe(
      PRICE_IDS.f28_1016_r2,
    );
  });

  it('§10.4 republishes 14/10 and 15/10 with their published figures unchanged', async () => {
    expect((await run('2026-10-14', '2026-10-15')).status).toBe('COMPLETED');

    const summary = published(await portfolioApi.getSummary('2026-10-15'));
    expect(summary).toMatchObject({
      stale: false,
      cash_balance: '199650.3745326500',
      aum: '1491965.8654717340',
      daily_pnl: '-8034.1345282660',
      cumulative_pnl: '-8034.1345282660',
    });
    expect(summary.published_at).not.toBe('2026-10-16T18:40:00-03:00');
    expect(published(await portfolioApi.getSummary('2026-10-14')).aum).toBe('1500000.0000000000');
  });

  it('§10.3 does not duplicate Pendências when ranges are processed again', async () => {
    await run('2026-10-17', '2026-10-18');
    await run('2026-10-17', '2026-10-18');
    const stalePredecessors = (await processingApi.listIssues()).items.filter(
      (i) => i.issue_type === 'STALE_PREDECESSOR',
    );
    expect(stalePredecessors.map((i) => i.affected_date)).toEqual(['2026-10-17']);

    await run('2026-10-16', '2026-10-18');
    await run('2026-10-16', '2026-10-18');
    await run('2026-10-17', '2026-10-18');

    expect(await missingPrices()).toHaveLength(5);
    expect((await processingApi.listIssues()).items).not.toContainEqual(
      expect.objectContaining({ issue_type: 'STALE_PREDECESSOR' }),
    );
  });

  it.each<[string, () => Promise<unknown>, string]>([
    [
      'POST /trades',
      () =>
        ledgerApi.createTrade({
          asset_id: IDS.di1f28,
          trade_date: '2026-10-17',
          trade_time: '10:00:00',
          signed_quantity: 1,
          input_kind: 'PU',
          execution_pu: '89000.00',
        }),
      '17/10/2026',
    ],
    [
      'DELETE /trades/:id',
      () => ledgerApi.deleteTrade('7a000000-0000-4000-8000-000000000003'),
      '16/10/2026',
    ],
    [
      'POST /ledger/deletions',
      () =>
        ledgerApi.deleteEntries({
          trade_ids: [],
          cash_movement_ids: ['7c000000-0000-4000-8000-000000000002'],
        }),
      '16/10/2026',
    ],
    [
      'POST /reference-prices',
      () =>
        pricesApi.setReferencePrice({
          asset_id: IDS.di1f29,
          reference_date: '2026-10-16',
          input_kind: 'PU',
          pu: '80300.00',
        }),
      '16/10/2026',
    ],
    [
      'DELETE /reference-prices/:id',
      () => pricesApi.removeReferencePrice(PRICE_IDS.f28_1016_r2),
      '16/10/2026',
    ],
  ])('§10.4 the mock fails a job after a write through %s', async (_path, write, shown) => {
    await write();

    const job = await run('2026-10-16', '2026-10-18');

    expect(job.status).toBe('FAILED');
    expect(job.error_message).toContain(`a partir de ${shown}`);
    expect((await portfolioApi.getSummary('2026-10-18')).publication).toBe('NOT_PROCESSED');
  });

  it('§10.4 a write made while the job is queued fails it rather than superseding it', async () => {
    const job = await processingApi.enqueue({ start_date: '2026-10-16', end_date: '2026-10-18' });
    await ledgerApi.createCashMovement({
      movement_date: '2026-10-17',
      movement_type: 'DEPOSIT',
      amount: '1000.00',
    });

    let current = job;
    for (let i = 0; i < 50 && !FINAL.includes(current.status); i += 1) {
      current = await processingApi.getRequest(job.id);
    }

    expect(current.status).toBe('FAILED');
  });

  it.each([
    ['2026-10-17', '2026-10-16', '2026-10-18', '17/10/2026'],
    ['2026-10-15', '2026-10-16', '2026-10-16', '15/10/2026'],
  ])(
    '§10.4 the mock fails a job whose range depends on a day changed since the seed (%s)',
    async (changed, start, end, shown) => {
      await ledgerApi.createCashMovement({
        movement_date: changed,
        movement_type: 'DEPOSIT',
        amount: '1000.00',
      });
      const issuesBefore = (await processingApi.listIssues()).items;

      const job = await run(start, end);

      expect(job).toMatchObject({
        status: 'FAILED',
        error_message: `Backend simulado: os resultados a partir de ${shown} dependem de lançamentos ou preços alterados e só podem ser recalculados pelo backend real. Nenhum dia foi publicado.`,
      });
      // All or nothing (§10.4): no day of the range was published.
      expect(published(await portfolioApi.getSummary('2026-10-16')).trades_pnl).toBe(
        '-394.7129232316',
      );
      expect((await portfolioApi.getSummary('2026-10-18')).publication).toBe('NOT_PROCESSED');
      expect((await processingApi.listIssues()).items).toEqual(issuesBefore);
    },
  );
});

describe('mock ids', () => {
  it('§11.1 gives every job a distinct short id (its first 8 characters), as real UUIDs do', async () => {
    await processingApi.enqueue({ start_date: '2026-10-14', end_date: '2026-10-14' });
    await processingApi.enqueue({ start_date: '2026-10-15', end_date: '2026-10-15' });

    const { items } = await processingApi.listRequests();
    const shortIds = items.map((job) => job.id.slice(0, 8));
    expect(new Set(shortIds).size).toBe(items.length);
  });
});

describe('mock ledger entries (GET /ledger/entries)', () => {
  const FULL = { start_date: '2026-10-14', end_date: '2026-10-16' };

  it('§11.3 merges trades and cash movements: newest date first, trades before cash in a date', async () => {
    const { items } = await ledgerApi.listEntries(FULL);

    expect(items.map((e) => [e.kind, e.date, e.time])).toEqual([
      ['TRADE', '2026-10-16', '15:00:00'],
      ['CASH_MOVEMENT', '2026-10-16', null],
      ['TRADE', '2026-10-15', '10:30:00'],
      ['TRADE', '2026-10-14', '14:10:00'],
      ['CASH_MOVEMENT', '2026-10-14', null],
    ]);
  });

  it('§6.1 orders the trades of one date by time, then seq, newest first', async () => {
    const trade = {
      asset_id: IDS.di1f28,
      trade_date: '2026-10-16',
      signed_quantity: 1,
      input_kind: 'PU',
      execution_pu: '89000.00',
    } as const;
    const early = await ledgerApi.createTrade({ ...trade, trade_time: '10:00:00' });
    const later = await ledgerApi.createTrade({ ...trade, trade_time: '10:00:00' });

    const { items } = await ledgerApi.listEntries({ ...FULL, start_date: '2026-10-16' });

    expect(items.flatMap((e) => (e.kind === 'TRADE' ? [e.seq] : []))).toEqual([
      3,
      later.seq,
      early.seq,
    ]);
  });

  it('§11.3 order=asc is the exact reverse of the default order', async () => {
    const desc = (await ledgerApi.listEntries(FULL)).items.map((e) => e.id);
    const asc = (await ledgerApi.listEntries({ ...FULL, order: 'asc' })).items.map((e) => e.id);

    expect(asc).toEqual([...desc].reverse());
  });

  it('§11.3 gives every row its signed cash effect: the trade cash_amount, ±amount for cash', async () => {
    const { items } = await ledgerApi.listEntries(FULL);

    expect(items.map((e) => e.cash_amount)).toEqual([
      '356408.8906133732',
      '-50000.00',
      '-410285.00',
      '-890064.6254673500',
      '1500000.00',
    ]);
  });

  it('§11.3 applies the inclusive range and the search on the server', async () => {
    const oneDay = await ledgerApi.listEntries({
      start_date: '2026-10-14',
      end_date: '2026-10-14',
    });
    const byAsset = await ledgerApi.listEntries({ ...FULL, search: 'DI1F28' });
    const byType = await ledgerApi.listEntries({ ...FULL, search: 'retirada' });

    expect(oneDay.items).toHaveLength(2);
    expect(byAsset.items.map((e) => e.kind === 'TRADE' && e.asset_code)).toEqual([
      'DI1F28',
      'DI1F28',
    ]);
    expect(byType.items.map((e) => e.kind === 'CASH_MOVEMENT' && e.movement_type)).toEqual([
      'WITHDRAWAL',
    ]);
  });

  it('OQ-11 rejects a range that starts after it ends', async () => {
    const problem = await problemOf(
      ledgerApi.listEntries({ start_date: '2026-10-16', end_date: '2026-10-15' }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'INVALID_RANGE', field: 'start_date' });
  });
});
