import type {
  PortfolioPositions,
  PortfolioSummary,
  ProcessingChain,
  ProcessingRequest,
  ProcessingScope,
} from '../contract';
import { assetsApi, ledgerApi, portfolioApi, pricesApi, processingApi } from '../endpoints';
import { ApiError } from '../http';
import { db, setStatus } from './db';
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

/**
 * The summary as one flat record, as these tests were written before OQ-21 split it: cash from
 * the cash chain, the rest from the positions chain.
 */
function flat(summary: PortfolioSummary) {
  return {
    published_at: summary.positions.published_at,
    cash_balance: summary.cash.balance,
    positions_market_value: summary.positions.market_value,
    aum: summary.aum,
    position_pnl: summary.positions.position_pnl,
    trades_pnl: summary.positions.trades_pnl,
    daily_pnl: summary.positions.daily_pnl,
    cumulative_pnl: summary.positions.cumulative_pnl,
    valuation_status: summary.positions.valuation_status,
    pnl_status: summary.positions.pnl_status,
  };
}

/** The processing status of each chain on a date (OQ-21, OQ-31). */
async function chainStatus(date: string) {
  const summary = await portfolioApi.getSummary(date);
  return { cash: summary.cash.status, positions: summary.positions.status };
}

function published(value: PortfolioPositions): PortfolioPositions {
  if (value.status === 'NOT_PROCESSED') throw new Error('expected a published date');
  return value;
}

describe('mock portfolio', () => {
  it('§8.2 §11.4 returns the published summary of a complete day', async () => {
    const summary = flat(await portfolioApi.getSummary('2026-10-15'));

    expect(summary).toMatchObject({
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
    const summary = flat(await portfolioApi.getSummary('2026-10-16'));

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

  it('OQ-31 a price corrected after publication changes no status', async () => {
    expect(await chainStatus('2026-10-16')).toEqual({
      cash: 'PROCESSED',
      positions: 'PROCESSED_WITH_ISSUES',
    });
  });

  it('§12 D3 reports a date that was never processed instead of inventing figures', async () => {
    const summary = await portfolioApi.getSummary('2026-10-17');
    expect(summary.cash).toMatchObject({
      status: 'NOT_PROCESSED',
      balance: null,
      published_at: null,
    });
    expect(summary.positions.status).toBe('NOT_PROCESSED');
    expect(summary.positions.market_value).toBeNull();
  });

  it('OQ-41 returns one point per calendar date; the stored cumulative P&L stays null on gaps', async () => {
    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-12',
      end_date: '2026-10-18',
    });

    expect(items.map((p) => [p.date, p.cumulative_pnl])).toEqual([
      ['2026-10-12', null],
      ['2026-10-13', null],
      ['2026-10-14', '0.0000000000'],
      ['2026-10-15', '-8034.1345282660'],
      ['2026-10-16', null],
      ['2026-10-17', null],
      ['2026-10-18', null],
    ]);
  });

  it('OQ-41 an unprocessed date reads NOT_PROCESSED with every figure null but the range sum', async () => {
    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-17',
      end_date: '2026-10-17',
    });

    expect(items).toEqual([
      {
        date: '2026-10-17',
        status: 'NOT_PROCESSED',
        published_at: null,
        pnl_status: null,
        daily_pnl: null,
        cumulative_pnl: null,
        range_cumulative_pnl: '0',
      },
    ]);
  });
});

describe('OQ-21 positions and the P&L series use the same status as the summary', () => {
  it('§8.3 positions report the positions chain status and its processing time', async () => {
    expect(await portfolioApi.getPositions('2026-10-16')).toMatchObject({
      status: 'PROCESSED_WITH_ISSUES',
      published_at: '2026-10-16T18:40:00-03:00',
    });
    expect((await portfolioApi.getPositions('2026-10-15')).status).toBe('PROCESSED');
  });

  it('OQ-30 a position row shows the current preferred reference price, not the processed one', async () => {
    const positions = published(await portfolioApi.getPositions('2026-10-16'));
    const di1f28 = positions.items.find((row) => row.asset_code === 'DI1F28');

    // 16/10 was processed with 89.200,90; the price was corrected afterwards (MANUAL wins).
    expect(di1f28).toMatchObject({
      reference_source: 'MANUAL',
      reference_pu: '89250.3147019396',
      reference_rate: '0.0980',
      financial_total: '535205.4053049072',
    });
  });

  it('OQ-30 a reference price recorded after processing shows on the row at once', async () => {
    await pricesApi.setReferencePrice({
      asset_id: IDS.di1f29,
      reference_date: '2026-10-16',
      input_kind: 'PU',
      pu: '80300.00',
    });

    const positions = published(await portfolioApi.getPositions('2026-10-16'));
    expect(positions.items.find((row) => row.asset_code === 'DI1F29')).toMatchObject({
      reference_source: 'MANUAL',
      reference_pu: '80300.00',
      financial_total: null,
      valuation_status: 'MISSING',
    });
  });

  it('§12 D3 a day never processed: NOT_PROCESSED, no rows, no publication time', async () => {
    expect(await portfolioApi.getPositions('2026-10-17')).toEqual({
      date: '2026-10-17',
      status: 'NOT_PROCESSED',
      published_at: null,
      items: [],
    });
  });

  it('OQ-16 OQ-31 OQ-41 each P&L point carries its status and processing time', async () => {
    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-14',
      end_date: '2026-10-17',
    });

    expect(items.map((p) => [p.date, p.status, p.published_at])).toEqual([
      ['2026-10-14', 'PROCESSED', '2026-10-16T18:40:00-03:00'],
      ['2026-10-15', 'PROCESSED', '2026-10-16T18:40:00-03:00'],
      ['2026-10-16', 'PROCESSED_WITH_ISSUES', '2026-10-16T18:40:00-03:00'],
      ['2026-10-17', 'NOT_PROCESSED', null],
    ]);
  });

  it('OQ-41 range_cumulative_pnl sums the daily P&L from the start; a missing or null day adds 0', async () => {
    const fromFifteenth = await portfolioApi.getPnlSeries({
      start_date: '2026-10-15',
      end_date: '2026-10-18',
    });
    const fromTwelfth = await portfolioApi.getPnlSeries({
      start_date: '2026-10-12',
      end_date: '2026-10-16',
    });

    expect(fromFifteenth.items.map((p) => [p.date, p.range_cumulative_pnl])).toEqual([
      ['2026-10-15', '-8034.1345282660'],
      // 16/10 is processed with a null daily P&L; 17 and 18/10 are not processed.
      ['2026-10-16', '-8034.1345282660'],
      ['2026-10-17', '-8034.1345282660'],
      ['2026-10-18', '-8034.1345282660'],
    ]);
    expect(fromTwelfth.items.map((p) => [p.date, p.range_cumulative_pnl])).toEqual([
      ['2026-10-12', '0'],
      ['2026-10-13', '0'],
      ['2026-10-14', '0.0000000000'],
      ['2026-10-15', '-8034.1345282660'],
      ['2026-10-16', '-8034.1345282660'],
    ]);
  });

  it('OQ-41 item 2 a date with no status has no processing time, even over an older published row', async () => {
    setStatus('2026-10-15', 'POSITIONS', null);

    const { items } = await portfolioApi.getPnlSeries({
      start_date: '2026-10-15',
      end_date: '2026-10-15',
    });

    expect(items[0]).toMatchObject({
      status: 'NOT_PROCESSED',
      published_at: null,
      daily_pnl: null,
    });
  });

  it.each(['FAILED', 'RUNNING'] as const)(
    'OQ-41 item 4 a %s day shows its status with no P&L and adds 0, even over an older published row',
    async (status) => {
      setStatus('2026-10-15', 'POSITIONS', status);

      const { items } = await portfolioApi.getPnlSeries({
        start_date: '2026-10-14',
        end_date: '2026-10-15',
      });

      expect(items[1]).toEqual({
        date: '2026-10-15',
        status,
        published_at: '2026-10-16T18:40:00-03:00',
        pnl_status: null,
        daily_pnl: null,
        cumulative_pnl: null,
        range_cumulative_pnl: '0.0000000000',
      });
    },
  );
});

describe('OQ-35 Portfolio reads dated after today', () => {
  it('OQ-35 a summary or positions read after today is 422 FUTURE_DATE on date', async () => {
    const summary = await problemOf(portfolioApi.getSummary('2026-10-19'));
    const positions = await problemOf(portfolioApi.getPositions('2026-10-19'));

    for (const problem of [summary, positions]) {
      expect(problem.status).toBe(422);
      expect(problem.errors?.map((e) => [e.code, e.field])).toEqual([['FUTURE_DATE', 'date']]);
    }
  });

  it('OQ-35 a P&L series ending after today is 422 FUTURE_DATE on end_date only', async () => {
    const problem = await problemOf(
      portfolioApi.getPnlSeries({ start_date: '2026-10-19', end_date: '2026-10-20' }),
    );

    expect(problem.status).toBe(422);
    expect(problem.errors?.map((e) => [e.code, e.field])).toEqual([['FUTURE_DATE', 'end_date']]);
  });

  it('OQ-35 a P&L series starting after today but ending today is INVALID_RANGE', async () => {
    const problem = await problemOf(
      portfolioApi.getPnlSeries({ start_date: '2026-10-19', end_date: '2026-10-18' }),
    );

    expect(problem.errors?.map((e) => [e.code, e.field])).toEqual([
      ['INVALID_RANGE', 'start_date'],
    ]);
  });

  it('OQ-35 today is read as published; a date not processed reads Não processado', async () => {
    const summary = await portfolioApi.getSummary('2026-10-18');

    expect(summary.cash.status).toBe('NOT_PROCESSED');
    expect(summary.positions.status).toBe('NOT_PROCESSED');
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

  it('OQ-33 trims and upper-cases a new contract code', async () => {
    const created = await assetsApi.createInstrument({
      product_id: IDS.di1,
      code: '  di1f31 ',
      maturity_date: '2031-01-02',
    });

    expect(created.code).toBe('DI1F31');
    const duplicate = await problemOf(
      assetsApi.createInstrument({
        product_id: IDS.di1,
        code: 'Di1F31',
        maturity_date: '2031-01-02',
      }),
    );
    expect(duplicate.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'code' });
  });

  it('OQ-33 an unknown product_id in the body is 422 on product_id, with the other field errors', async () => {
    const problem = await problemOf(
      assetsApi.createInstrument({ product_id: 'missing', code: 'DI1F31', maturity_date: '' }),
    );

    expect(problem.status).toBe(422);
    expect(problem.errors?.map((e) => [e.code, e.field])).toEqual([
      ['VALIDATION_ERROR', 'product_id'],
      ['VALIDATION_ERROR', 'maturity_date'],
    ]);
  });

  it('OQ-33 search is a substring match ignoring case and accents', async () => {
    const byName = await assetsApi.listProducts({ search: 'taxa media' });
    const byClass = await assetsApi.listProducts({ search: 'JUROS' });
    const byCode = await assetsApi.listInstruments({ product_id: IDS.di1, search: 'f28' });

    expect(byName.items.map((p) => p.code)).toEqual(['DI1']);
    expect(byClass.items.map((p) => p.code)).toEqual(['DI1']);
    expect(byCode.items.map((i) => i.code)).toEqual(['DI1F28']);
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
    expect(items[0]?.preferred).toMatchObject({ source: 'MANUAL', rate: '0.0980' });
    expect(items[0]?.sources.map((p) => p.source).sort()).toEqual(['B3', 'MANUAL']);
  });

  it('OQ-26 adding a price replaces the current MANUAL one: the old row goes, a new id comes', async () => {
    const corrected = await pricesApi.setReferencePrice({
      asset_id: IDS.di1f28,
      reference_date: '2026-10-16',
      input_kind: 'PU',
      pu: '89260.00',
    });
    const [day] = (
      await pricesApi.listReferencePrices({
        asset_id: IDS.di1f28,
        start_date: '2026-10-16',
        end_date: '2026-10-16',
      })
    ).items;

    expect(corrected).toMatchObject({ source: 'MANUAL', pu: '89260.00' });
    expect(corrected.id).not.toBe(PRICE_IDS.f28_1016);
    expect(corrected).not.toHaveProperty('revision');
    expect(day?.sources.filter((p) => p.source === 'MANUAL')).toEqual([corrected]);
    expect((await problemOf(pricesApi.removeReferencePrice(PRICE_IDS.f28_1016))).status).toBe(404);
    // OQ-31: the write changes no status.
    expect(await chainStatus('2026-10-16')).toEqual({
      cash: 'PROCESSED',
      positions: 'PROCESSED_WITH_ISSUES',
    });
  });

  it('§5 removing a price deletes it; the other source then prevails', async () => {
    await pricesApi.removeReferencePrice(PRICE_IDS.f28_1016);
    const [day] = (
      await pricesApi.listReferencePrices({
        asset_id: IDS.di1f28,
        start_date: '2026-10-16',
        end_date: '2026-10-16',
      })
    ).items;

    expect(day?.sources.map((p) => p.source)).toEqual(['B3']);
    expect(day?.preferred.source).toBe('B3');
    expect((await problemOf(pricesApi.removeReferencePrice(PRICE_IDS.f28_1016))).status).toBe(404);
  });

  it('OQ-42 a price read accepts dates after today; those days come back empty', async () => {
    const future = await pricesApi.listReferencePrices({
      asset_id: IDS.di1f28,
      start_date: '2026-10-19',
      end_date: '2026-11-30',
    });
    const across = await pricesApi.listReferencePrices({
      asset_id: IDS.di1f28,
      start_date: '2026-10-16',
      end_date: '2026-10-25',
    });

    expect(future.items).toEqual([]);
    expect(across.items.map((d) => d.reference_date)).toEqual(['2026-10-16']);
  });

  it('OQ-42 a price read still refuses a start after its end', async () => {
    const problem = await problemOf(
      pricesApi.listReferencePrices({
        asset_id: IDS.di1f28,
        start_date: '2026-10-25',
        end_date: '2026-10-20',
      }),
    );

    expect(problem.errors?.map((e) => [e.code, e.field])).toEqual([
      ['INVALID_RANGE', 'start_date'],
    ]);
  });

  it('OQ-42 OQ-14 a price write dated after today is still refused', async () => {
    const problem = await problemOf(
      pricesApi.setReferencePrice({
        asset_id: IDS.di1f28,
        reference_date: '2026-10-19',
        input_kind: 'PU',
        pu: '89000.00',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'FUTURE_DATE', field: 'reference_date' });
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

  it('OQ-33 last_reference is null for every contract for now, prices or not', async () => {
    const { items } = await assetsApi.listInstruments({ product_id: IDS.di1 });

    expect(items.map((i) => [i.code, i.last_reference])).toEqual([
      ['DI1F27', null],
      ['DI1F28', null],
      ['DI1F29', null],
      ['DI1F30', null],
    ]);
    expect((await assetsApi.getInstrument(IDS.di1f28)).last_reference).toBeNull();
  });
});

describe('mock ledger validation', () => {
  it("OQ-14 the fake backend's today is the app's clock (São Paulo), not a fixed date", async () => {
    vi.setSystemTime(new Date('2026-10-25T12:00:00-03:00'));
    const cash = (date: string) =>
      ledgerApi.createEntry({ type: 'CASH', date, time: '10:00:00', cash_amount: '1.00' });

    await expect(cash('2026-10-25')).resolves.toMatchObject({ date: '2026-10-25' });
    expect((await problemOf(cash('2026-10-26'))).errors?.[0]).toMatchObject({
      code: 'FUTURE_DATE',
    });
  });

  const trade = {
    asset_id: IDS.di1f28,
    date: '2026-10-17',
    time: '10:00:00',
    signed_quantity: 1,
    input_kind: 'PU' as const,
    execution_pu: '89000.00',
  };

  it('OQ-14 rejects a date after today with FUTURE_DATE on the field', async () => {
    const problem = await problemOf(
      ledgerApi.createEntry({
        type: 'TRADE',
        ...trade,
        date: '2026-10-19',
      }),
    );

    expect(problem.status).toBe(422);
    expect(problem.errors).toEqual([
      {
        code: 'FUTURE_DATE',
        message: 'A data não pode ser posterior a hoje.',
        field: 'date',
      },
    ]);
  });

  it('OQ-3 rejects a PU with more than 10 decimals instead of rounding it', async () => {
    const problem = await problemOf(
      ledgerApi.createEntry({
        type: 'TRADE',
        ...trade,
        execution_pu: '89000.12345678901',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'execution_pu' });
  });

  it('OQ-3 rejects a typed rate with more than 12 decimals', async () => {
    const problem = await problemOf(
      ledgerApi.createEntry({
        type: 'TRADE',
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

    const problem = await problemOf(
      ledgerApi.createEntry({
        type: 'TRADE',
        ...trade,
        asset_id: matured.id,
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'CONTRACT_MATURED', field: 'date' });
  });

  it('OQ-1 on the maturity date takes the PU and stores the rate as 0', async () => {
    const maturing = await assetsApi.createInstrument({
      product_id: IDS.di1,
      code: 'DI1X26',
      maturity_date: '2026-10-17',
    });

    const byRate = await problemOf(
      ledgerApi.createEntry({
        type: 'TRADE',
        ...trade,
        asset_id: maturing.id,
        input_kind: 'RATE',
        execution_rate: '0.10',
      }),
    );
    const byPu = await ledgerApi.createEntry({
      type: 'TRADE',
      ...trade,
      asset_id: maturing.id,
      execution_pu: '100000',
    });

    expect(byRate.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'execution_rate' });
    expect(byPu).toMatchObject({ execution_pu: '100000', execution_rate: '0' });
  });

  it('OQ-3 rejects a cash amount with more than 2 decimals', async () => {
    const problem = await problemOf(
      ledgerApi.createEntry({
        type: 'CASH',
        date: '2026-10-17',
        time: '12:00:00',
        cash_amount: '10.001',
      }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'cash_amount' });
  });

  it('§10.1 OQ-31 a new trade changes no status and never starts a job', async () => {
    const before = (await processingApi.listRequests()).items.length;

    await ledgerApi.createEntry({
      type: 'TRADE',
      ...trade,
      date: '2026-10-15',
    });

    expect(await chainStatus('2026-10-15')).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED' });
    expect((await processingApi.listRequests()).items).toHaveLength(before);
  });

  it('§6.1 deletes several entries atomically: one unknown id deletes nothing', async () => {
    const range = { start_date: '2026-10-01', end_date: '2026-10-18' };
    const [first] = (await ledgerApi.listEntries(range)).items;

    const problem = await problemOf(ledgerApi.deleteEntries({ ids: [first?.id ?? '', 'missing'] }));

    expect(problem.status).toBe(404);
    expect((await ledgerApi.listEntries(range)).items).toHaveLength(5);
  });

  it('§6.1 deletes a trade and a cash entry in one request, by id alone', async () => {
    const range = { start_date: '2026-10-01', end_date: '2026-10-18' };

    await ledgerApi.deleteEntries({
      ids: ['7a000000-0000-4000-8000-000000000003', '7c000000-0000-4000-8000-000000000002'],
    });

    expect((await ledgerApi.listEntries(range)).items.map((e) => e.id)).not.toEqual(
      expect.arrayContaining([
        '7a000000-0000-4000-8000-000000000003',
        '7c000000-0000-4000-8000-000000000002',
      ]),
    );
    expect((await ledgerApi.listEntries(range)).items).toHaveLength(3);
  });

  it('OQ-32 an empty ids list is 422 VALIDATION_ERROR on ids', async () => {
    const problem = await problemOf(ledgerApi.deleteEntries({ ids: [] }));

    expect(problem.status).toBe(422);
    expect(problem.errors?.[0]).toMatchObject({ code: 'VALIDATION_ERROR', field: 'ids' });
  });

  it('OQ-32 a repeated id counts once: {ids: [X, X]} deletes X and succeeds', async () => {
    const range = { start_date: '2026-10-01', end_date: '2026-10-18' };
    const id = '7a000000-0000-4000-8000-000000000003';

    await ledgerApi.deleteEntries({ ids: [id, id] });

    const ids = (await ledgerApi.listEntries(range)).items.map((e) => e.id);
    expect(ids).not.toContain(id);
    expect(ids).toHaveLength(4);
  });

  it('OQ-32 the deletion is permanent: an already-deleted id answers 404 and nothing is deleted', async () => {
    const range = { start_date: '2026-10-01', end_date: '2026-10-18' };
    const gone = '7a000000-0000-4000-8000-000000000003';
    const kept = '7c000000-0000-4000-8000-000000000002';
    await ledgerApi.deleteEntries({ ids: [gone] });

    const problem = await problemOf(ledgerApi.deleteEntries({ ids: [kept, gone] }));

    expect(problem.status).toBe(404);
    expect(problem.errors?.[0]?.code).toBe('NOT_FOUND');
    expect((await ledgerApi.listEntries(range)).items.map((e) => e.id)).toContain(kept);
  });

  it('§6.2 a cash entry needs a time and a non-zero amount with at most 2 places', async () => {
    const problem = await problemOf(
      ledgerApi.createEntry({ type: 'CASH', date: '2026-10-17', time: '', cash_amount: '0' }),
    );

    expect(problem.errors?.map((e) => e.field)).toEqual(['time', 'cash_amount']);
  });

  it('§6.2 records a retirada as a negative amount, with its time', async () => {
    const entry = await ledgerApi.createEntry({
      type: 'CASH',
      date: '2026-10-17',
      time: '11:05',
      cash_amount: '-250.50',
    });

    expect(entry).toMatchObject({ type: 'CASH', time: '11:05:00', cash_amount: '-250.50' });
  });
});

describe('mock processing', () => {
  it('P21 pages the jobs newest first, by (created_at, id)', async () => {
    const all = (await processingApi.listRequests()).items;
    const first = await processingApi.listRequests({ limit: 2 });
    const rest = await processingApi.listRequests({ limit: 50, cursor: first.next_cursor ?? '' });

    expect([...first.items, ...rest.items].map((j) => j.id)).toEqual(all.map((j) => j.id));
    expect(rest.next_cursor).toBeNull();
    const created = all.map((j) => j.created_at);
    expect(created).toEqual([...created].sort().reverse());
  });

  async function poll(id: string): Promise<ProcessingRequest> {
    return processingApi.getRequest(id);
  }

  it('§10.2 OQ-23 runs one queued job date by date to completion', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      scope: 'ALL',
    });
    expect(job).toMatchObject({ status: 'QUEUED', progress_date: null });

    // No dispatcher (OQ-46): the worker takes the queued run straight to RUNNING.
    const started = await poll(job.id);
    expect(started).toMatchObject({ status: 'RUNNING', progress_date: null, dispatched_at: null });
    expect(started.started_at).not.toBeNull();
    expect(await poll(job.id)).toMatchObject({ status: 'RUNNING', progress_date: '2026-10-14' });
    expect(await poll(job.id)).toMatchObject({ status: 'COMPLETED', progress_date: '2026-10-15' });
  });

  it('OQ-46 a run never reads DISPATCHED or CANCELLING', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-16',
      scope: 'ALL',
    });
    const seen = new Set<string>([job.status]);
    seen.add((await poll(job.id)).status);
    seen.add((await processingApi.cancel(job.id)).status);
    for (let i = 0; i < 5; i += 1) seen.add((await poll(job.id)).status);

    expect([...seen]).toEqual(['QUEUED', 'RUNNING', 'CANCELLED']);
  });

  it('§10.3 ends with COMPLETED_WITH_ISSUES when the range has a missing price', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-16',
      end_date: '2026-10-16',
      scope: 'ALL',
    });
    for (let i = 0; i < 3; i += 1) await poll(job.id);

    expect((await poll(job.id)).status).toBe('COMPLETED_WITH_ISSUES');
  });

  it('§10.2 cancels a queued job at once and a running one cooperatively', async () => {
    const queued = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-16',
      scope: 'ALL',
    });
    const second = await processingApi.enqueue({
      start_date: '2026-10-15',
      end_date: '2026-10-16',
      scope: 'ALL',
    });
    await poll(queued.id); // RUNNING, 14/10 being processed

    expect((await processingApi.cancel(second.id)).status).toBe('CANCELLED');
    // OQ-46: a running run stays RUNNING with its cancel request set.
    const requested = await processingApi.cancel(queued.id);
    expect(requested.status).toBe('RUNNING');
    expect(requested.cancel_requested_at).not.toBeNull();
    // The current date commits; later dates are untouched.
    expect(await poll(queued.id)).toMatchObject({
      status: 'CANCELLED',
      progress_date: '2026-10-14',
    });
  });

  it('OQ-46 a second cancel of a running run answers 409 JOB_NOT_CANCELLABLE', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      scope: 'ALL',
    });
    await poll(job.id); // RUNNING
    await processingApi.cancel(job.id);

    const problem = await problemOf(processingApi.cancel(job.id));

    expect(problem.status).toBe(409);
    expect(problem.errors?.[0]).toMatchObject({
      code: 'JOB_NOT_CANCELLABLE',
      message: 'O cancelamento deste processamento já foi solicitado.',
    });
  });

  it('§10.2 runs one job at a time: the next stays queued until the active one ends', async () => {
    const first = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      scope: 'ALL',
    });
    const second = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-14',
      scope: 'ALL',
    });

    expect((await poll(first.id)).status).toBe('RUNNING');
    expect((await poll(second.id)).status).toBe('QUEUED'); // first commits 14/10
    expect((await poll(second.id)).status).toBe('QUEUED'); // first commits 15/10 and ends
    expect((await poll(first.id)).status).toBe('COMPLETED'); // the worker takes the next
    // The second run started only then: its single date commits on this read.
    expect(await poll(second.id)).toMatchObject({
      status: 'COMPLETED',
      progress_date: '2026-10-14',
    });
  });

  it('OQ-23 OQ-31 a write during a run changes no status; the run goes on (no SUPERSEDED)', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-14',
      end_date: '2026-10-15',
      scope: 'POSITIONS',
    });
    await poll(job.id); // RUNNING

    await ledgerApi.createEntry({
      type: 'CASH',
      date: '2026-10-15',
      time: '12:00:00',
      cash_amount: '1000.00',
    });
    await poll(job.id);

    expect((await poll(job.id)).status).toBe('COMPLETED');
    expect(await chainStatus('2026-10-15')).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED' });
  });

  it('OQ-31 runs a range whose day before was processed with issues', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-17',
      end_date: '2026-10-17',
      scope: 'ALL',
    });
    for (let i = 0; i < 3; i += 1) await poll(job.id);

    expect((await poll(job.id)).status).toBe('COMPLETED_WITH_ISSUES');
  });

  it('OQ-44 a technical failure carries PROCESSING_ERROR and its pt-BR message', async () => {
    const failed = (await processingApi.listRequests()).items.find((r) => r.status === 'FAILED');

    // The seeded run failed outside every chain: a date, no chain (OQ-40 item 3).
    expect(failed).toMatchObject({
      error_code: 'PROCESSING_ERROR',
      error_message: 'Erro técnico ao processar a data.',
      failed_date: '2026-10-01',
      failed_chain: null,
    });
  });

  it('OQ-45 no run carries the retired RECOVERY_EXHAUSTED', async () => {
    const codes = (await processingApi.listRequests()).items.map((r) => r.error_code);

    expect(codes).not.toContain('RECOVERY_EXHAUSTED');
  });

  it('§10.2 refuses to cancel a finished job with JOB_NOT_CANCELLABLE', async () => {
    const { items } = await processingApi.listRequests();
    const finished = items.find((r) => r.status === 'COMPLETED');

    const problem = await problemOf(processingApi.cancel(finished?.id ?? ''));

    expect(problem.status).toBe(409);
    expect(problem.errors?.[0]?.code).toBe('JOB_NOT_CANCELLABLE');
  });

  it.each([
    ['2026-10-14', 'ZERO_STATE'],
    ['2026-10-16', 'PROCESSED'],
    ['2026-10-17', 'PROCESSED_WITH_ISSUES'],
    ['2026-10-18', 'NOT_PROCESSED'],
  ])('OQ-11 OQ-26 previews a range starting %s with predecessor %s', async (start, state) => {
    const preview = await processingApi.preview({
      start_date: start,
      end_date: '2026-10-18',
      scope: 'ALL',
    });

    expect(preview.predecessor.positions).toBe(state);
  });

  it('OQ-11 rejects a range that starts after it ends', async () => {
    const problem = await problemOf(
      processingApi.preview({ start_date: '2026-10-16', end_date: '2026-10-15', scope: 'ALL' }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'INVALID_RANGE', field: 'start_date' });
  });

  it('OQ-37 a missing price shows once per (asset, needed date), at its earliest affected date', async () => {
    const base = db.issues[0];
    if (!base) throw new Error('the fixtures have one issue');
    // 17/10's P&L needs the same 16/10 DI1F29 price as 16/10's valuation.
    db.issues.push(
      { ...base, id: 'dup-1', affected_date: '2026-10-17' },
      { ...base, id: 'other-date', affected_date: '2026-10-17', required_price_date: '2026-10-17' },
    );

    const { items } = await processingApi.listIssues();

    expect(items.map((i) => [i.asset_code, i.required_price_date, i.affected_date])).toEqual([
      ['DI1F29', '2026-10-17', '2026-10-17'],
      ['DI1F29', '2026-10-16', '2026-10-16'],
    ]);
  });

  it('OQ-37 an expired open position shows once per asset, at its earliest affected date', async () => {
    const expired = (id: string, date: string) => ({
      id,
      issue_type: 'EXPIRED_OPEN_POSITION' as const,
      asset_id: IDS.di1f27,
      asset_code: 'DI1F27',
      affected_date: date,
      required_price_date: null,
      request_id: 'r',
    });
    db.issues.push(
      expired('e3', '2027-01-07'),
      expired('e1', '2027-01-05'),
      expired('e2', '2027-01-06'),
    );

    const { items } = await processingApi.listIssues();

    const rows = items.filter((i) => i.issue_type === 'EXPIRED_OPEN_POSITION');
    expect(rows.map((i) => [i.asset_code, i.affected_date])).toEqual([['DI1F27', '2027-01-05']]);
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
  const FINAL = ['COMPLETED', 'COMPLETED_WITH_ISSUES', 'CANCELLED', 'FAILED'];

  /** Queues [start, end] and polls it until it reaches a final status. */
  async function run(
    start: string,
    end: string,
    scope: ProcessingScope = 'ALL',
  ): Promise<ProcessingRequest> {
    const job = await processingApi.enqueue({ start_date: start, end_date: end, scope });
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

  it('§10.4 OQ-12 republishes 16/10 with the corrected price and a new processing time', async () => {
    expect((await run('2026-10-16', '2026-10-18')).status).toBe('COMPLETED_WITH_ISSUES');

    const summary = flat(await portfolioApi.getSummary('2026-10-16'));
    expect(summary).toMatchObject({
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

      expect(flat(await portfolioApi.getSummary(date))).toMatchObject({
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
    expect(items.map((p) => [p.date, p.cumulative_pnl, p.status])).toEqual([
      ['2026-10-14', '0.0000000000', 'PROCESSED'],
      ['2026-10-15', '-8034.1345282660', 'PROCESSED'],
      ['2026-10-16', null, 'PROCESSED_WITH_ISSUES'],
      ['2026-10-17', null, 'PROCESSED_WITH_ISSUES'],
      ['2026-10-18', null, 'PROCESSED_WITH_ISSUES'],
    ]);
  });

  it('OQ-31 after 16/10 processed with issues, 17–18/10 process and read with issues', async () => {
    expect((await run('2026-10-17', '2026-10-18')).status).toBe('COMPLETED_WITH_ISSUES');

    for (const date of ['2026-10-16', '2026-10-17', '2026-10-18']) {
      expect(await chainStatus(date)).toEqual({
        cash: 'PROCESSED',
        positions: 'PROCESSED_WITH_ISSUES',
      });
    }
  });

  it('OQ-31 a range after an unprocessed day fails until the gap is processed', async () => {
    await run('2026-10-16', '2026-10-16');
    expect(
      (
        await processingApi.preview({
          start_date: '2026-10-17',
          end_date: '2026-10-17',
          scope: 'ALL',
        })
      ).predecessor,
    ).toEqual({ cash: 'PROCESSED', positions: 'PROCESSED_WITH_ISSUES' });

    // 17/10 was never processed: a run starting 18/10 fails on its first day.
    const positionsJob = await processingApi.enqueue({
      start_date: '2026-10-18',
      end_date: '2026-10-18',
      scope: 'POSITIONS',
    });
    let failed = positionsJob;
    for (let i = 0; i < 10; i += 1) failed = await processingApi.getRequest(positionsJob.id);
    expect(failed).toMatchObject({
      status: 'FAILED',
      error_code: 'POSITIONS_PREDECESSOR_MISSING',
    });
    expect(await chainStatus('2026-10-18')).toEqual({
      cash: 'NOT_PROCESSED',
      positions: 'FAILED',
    });

    await run('2026-10-17', '2026-10-18');
    // 18/10 has no prices, so positions read Processado com pendências (OQ-23).
    expect(await chainStatus('2026-10-18')).toEqual({
      cash: 'PROCESSED',
      positions: 'PROCESSED_WITH_ISSUES',
    });
  });

  it('§7 publishes the days before the first entry as the zero state', async () => {
    expect((await run('2026-10-10', '2026-10-13')).status).toBe('COMPLETED');

    expect(flat(await portfolioApi.getSummary('2026-10-12'))).toMatchObject({
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
    await ledgerApi.createEntry({
      type: 'CASH',
      date: '2026-10-17',
      time: '12:00:00',
      cash_amount: '1000.00',
    });

    expect((await run('2026-10-14', '2026-10-16')).status).toBe('COMPLETED_WITH_ISSUES');
    const summary = flat(await portfolioApi.getSummary('2026-10-16'));
    expect(summary).toMatchObject({ trades_pnl: '-592.3681943852' });
    const rows = published(await portfolioApi.getPositions('2026-10-16')).items;
    // OQ-30: the row shows the current preferred price (the corrected one) and its source.
    const row = rows.find((r) => r.asset_code === 'DI1F28');
    expect(row).toMatchObject({ reference_source: 'MANUAL', reference_pu: '89250.3147019396' });
    expect(row).not.toHaveProperty('reference_price_id');
  });

  it('§10.4 republishes 14/10 and 15/10 with their published figures unchanged', async () => {
    expect((await run('2026-10-14', '2026-10-15')).status).toBe('COMPLETED');

    const summary = flat(await portfolioApi.getSummary('2026-10-15'));
    expect(summary).toMatchObject({
      cash_balance: '199650.3745326500',
      aum: '1491965.8654717340',
      daily_pnl: '-8034.1345282660',
      cumulative_pnl: '-8034.1345282660',
    });
    expect(summary.published_at).not.toBe('2026-10-16T18:40:00-03:00');
    expect(flat(await portfolioApi.getSummary('2026-10-14')).aum).toBe('1500000.0000000000');
  });

  it('§10.3 OQ-26 does not duplicate Pendências: a reprocessed date replaces its issues', async () => {
    await run('2026-10-17', '2026-10-18');
    await run('2026-10-17', '2026-10-18');
    await run('2026-10-16', '2026-10-18');
    await run('2026-10-16', '2026-10-18');
    await run('2026-10-17', '2026-10-18');

    expect(await missingPrices()).toHaveLength(5);
  });

  // A trade changes both chains, so an ALL run fails; a cash entry or a price changes one, so
  // the other chain goes on to the end (OQ-36).
  it.each<[string, () => Promise<unknown>, string, string, ProcessingChain]>([
    [
      'POST /ledger/entries (TRADE)',
      () =>
        ledgerApi.createEntry({
          type: 'TRADE',
          asset_id: IDS.di1f28,
          date: '2026-10-17',
          time: '10:00:00',
          signed_quantity: 1,
          input_kind: 'PU',
          execution_pu: '89000.00',
        }),
      '17/10/2026',
      'FAILED',
      'POSITIONS',
    ],
    [
      'POST /ledger/entries/deletions (a trade)',
      () => ledgerApi.deleteEntries({ ids: ['7a000000-0000-4000-8000-000000000003'] }),
      '16/10/2026',
      'FAILED',
      'POSITIONS',
    ],
    [
      'POST /ledger/entries/deletions (a cash entry)',
      () => ledgerApi.deleteEntries({ ids: ['7c000000-0000-4000-8000-000000000002'] }),
      '16/10/2026',
      'COMPLETED_WITH_ISSUES',
      'CASH',
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
      'COMPLETED_WITH_ISSUES',
      'POSITIONS',
    ],
    [
      'DELETE /reference-prices/:id',
      () => pricesApi.removeReferencePrice(PRICE_IDS.f28_1016),
      '16/10/2026',
      'COMPLETED_WITH_ISSUES',
      'POSITIONS',
    ],
  ])(
    'OQ-23 OQ-36 the mock fails a chain at the first date a write through %s changed',
    async (_path, write, shown, ending, chain) => {
      await write();

      const job = await run('2026-10-16', '2026-10-18');

      expect(job).toMatchObject({ status: ending, failed_chain: chain });
      expect(job.error_message).toContain(`Backend simulado: ${shown} depende`);
      // The failed chain's later dates are untouched (OQ-23 item 5, OQ-36 item 1).
      const after = await portfolioApi.getSummary('2026-10-18');
      expect(chain === 'CASH' ? after.cash.status : after.positions.status).toBe('NOT_PROCESSED');
    },
  );

  it('OQ-36 a cash write made while an ALL job is queued fails its cash there; positions go on', async () => {
    const job = await processingApi.enqueue({
      start_date: '2026-10-16',
      end_date: '2026-10-18',
      scope: 'ALL',
    });
    await ledgerApi.createEntry({
      type: 'CASH',
      date: '2026-10-17',
      time: '12:00:00',
      cash_amount: '1000.00',
    });

    let current = job;
    for (let i = 0; i < 50 && !FINAL.includes(current.status); i += 1) {
      current = await processingApi.getRequest(job.id);
    }

    expect(current).toMatchObject({
      status: 'COMPLETED_WITH_ISSUES',
      progress_date: '2026-10-18',
      failed_date: '2026-10-17',
      failed_chain: 'CASH',
    });
    expect((await chainStatus('2026-10-18')).cash).toBe('NOT_PROCESSED');
  });

  it.each([
    ['2026-10-17', '2026-10-16', '2026-10-18', '17/10/2026', '2026-10-16'],
    ['2026-10-15', '2026-10-16', '2026-10-16', '16/10/2026', null],
  ])(
    'OQ-23 the mock fails a cash run at the first date changed since the seed (%s): earlier dates stay',
    async (changed, start, end, shown, committed) => {
      await ledgerApi.createEntry({
        type: 'CASH',
        date: changed,
        time: '12:00:00',
        cash_amount: '1000.00',
      });

      const job = await run(start, end, 'CASH');

      expect(job).toMatchObject({
        status: 'FAILED',
        progress_date: committed,
        error_code: 'MOCK_INPUTS_CHANGED',
        error_message: `Backend simulado: ${shown} depende de lançamentos ou preços alterados e só pode ser recalculado pelo backend real. As datas anteriores continuam publicadas.`,
      });
      const failed = committed === null ? start : '2026-10-17';
      expect((await chainStatus(failed)).cash).toBe('FAILED');
      // The failed date keeps its previously published data (OQ-23 item 2).
      if (committed === null) {
        expect(flat(await portfolioApi.getSummary('2026-10-16')).trades_pnl).toBe(
          '-394.7129232316',
        );
      }
      expect((await portfolioApi.getSummary('2026-10-18')).positions.status).toBe('NOT_PROCESSED');
    },
  );
});

describe('mock ids', () => {
  it('§11.1 gives every job a distinct short id (its first 8 characters), as real UUIDs do', async () => {
    await processingApi.enqueue({ start_date: '2026-10-14', end_date: '2026-10-14', scope: 'ALL' });
    await processingApi.enqueue({ start_date: '2026-10-15', end_date: '2026-10-15', scope: 'ALL' });

    const { items } = await processingApi.listRequests();
    const shortIds = items.map((job) => job.id.slice(0, 8));
    expect(new Set(shortIds).size).toBe(items.length);
  });
});

describe('mock ledger entries (GET /ledger/entries)', () => {
  const FULL = { start_date: '2026-10-14', end_date: '2026-10-16' };

  it('P21 pages by keyset: following next_cursor reads every entry once, in order', async () => {
    const all = (await ledgerApi.listEntries(FULL)).items.map((e) => e.id);
    const seen: string[] = [];
    let cursor: string | null = null;
    let pages = 0;
    do {
      const page = await ledgerApi.listEntries({
        ...FULL,
        limit: 2,
        ...(cursor ? { cursor } : {}),
      });
      seen.push(...page.items.map((e) => e.id));
      cursor = page.next_cursor;
      pages += 1;
    } while (cursor !== null);

    expect(pages).toBe(3);
    expect(seen).toEqual(all);
  });

  it('P21 the last page has no next_cursor', async () => {
    expect((await ledgerApi.listEntries(FULL)).next_cursor).toBeNull();
    expect((await ledgerApi.listEntries({ ...FULL, limit: 5 })).next_cursor).toBeNull();
  });

  it('P21 rejects a limit out of 1–200 and an unknown cursor', async () => {
    const badLimit = await problemOf(ledgerApi.listEntries({ ...FULL, limit: 0 }));
    const badCursor = await problemOf(ledgerApi.listEntries({ ...FULL, cursor: 'bm9wZQ==' }));

    expect(badLimit.errors?.[0]).toMatchObject({ field: 'limit' });
    expect(badCursor.errors?.[0]).toMatchObject({ field: 'cursor' });
  });

  it('§11.3 lists both types in one order, by date and time, newest first', async () => {
    const { items } = await ledgerApi.listEntries(FULL);

    expect(items.map((e) => [e.type, e.date, e.time])).toEqual([
      ['CASH', '2026-10-16', '17:30:00'],
      ['TRADE', '2026-10-16', '15:00:00'],
      ['TRADE', '2026-10-15', '10:30:00'],
      ['TRADE', '2026-10-14', '14:10:00'],
      ['CASH', '2026-10-14', '09:00:00'],
    ]);
  });

  it('§6.1 orders the entries of one date by time, then seq, newest first', async () => {
    const trade = {
      asset_id: IDS.di1f28,
      date: '2026-10-16',
      signed_quantity: 1,
      input_kind: 'PU',
      execution_pu: '89000.00',
    } as const;
    const early = await ledgerApi.createEntry({
      type: 'TRADE',
      ...trade,
      time: '10:00:00',
    });
    const later = await ledgerApi.createEntry({
      type: 'TRADE',
      ...trade,
      time: '10:00:00',
    });

    const { items } = await ledgerApi.listEntries({ ...FULL, start_date: '2026-10-16' });

    expect(items.map((e) => e.seq)).toEqual([5, 4, later.seq, early.seq]);
  });

  it('§11.3 order=asc is the exact reverse of the default order', async () => {
    const desc = (await ledgerApi.listEntries(FULL)).items.map((e) => e.id);
    const asc = (await ledgerApi.listEntries({ ...FULL, order: 'asc' })).items.map((e) => e.id);

    expect(asc).toEqual([...desc].reverse());
  });

  it('§11.3 gives every row its signed cash effect, trade or cash', async () => {
    const { items } = await ledgerApi.listEntries(FULL);

    expect(items.map((e) => e.cash_amount)).toEqual([
      '-50000.00',
      '356408.8906133732',
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
    expect(byAsset.items.map((e) => e.type === 'TRADE' && e.asset_code)).toEqual([
      'DI1F28',
      'DI1F28',
    ]);
    expect(byType.items.map((e) => e.cash_amount)).toEqual(['-50000.00']);
  });

  it('OQ-11 rejects a range that starts after it ends', async () => {
    const problem = await problemOf(
      ledgerApi.listEntries({ start_date: '2026-10-16', end_date: '2026-10-15' }),
    );

    expect(problem.errors?.[0]).toMatchObject({ code: 'INVALID_RANGE', field: 'start_date' });
  });
});
