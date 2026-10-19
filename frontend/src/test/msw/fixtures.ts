import type {
  CashLedgerEntry,
  Instrument,
  InstrumentType,
  Issue,
  LedgerEntry,
  PnlPoint,
  PortfolioPositions,
  PortfolioSummary,
  ProcessingPreview,
  ProcessingRequest,
  Product,
  ReferencePrice,
  ReferencePriceDay,
  TradeLedgerEntry,
} from '@/api/contract';

// Static API answers for the component tests, typed with the contract. They are what the real
// backend returns for one small story; nothing here is computed, and no handler changes them.
// Figures were computed offline with the spec's formulas (§4.1 DC/365, §7, §8; Decimal 34
// digits, ROUND_HALF_UP, PU 10 dp, rate 12 dp, OQ-3). A test that needs another answer, or the
// answer after a write, serves it itself with `server.use(...)`.
//
// Story (today = 18/10/2026):
//   14/10  Aporte 1.500.000,00; compra 10 DI1F28 a 10,00% a.a.
//   15/10  Compra 5 DI1F29 a PU 82.057,00
//   16/10  Venda 4 DI1F28 a 9,95% a.a.; retirada 50.000,00. No DI1F29 price: positions
//          processed with issues, P&L null. DI1F28's price corrected after 16/10 was processed.
//   17/10, 18/10  not processed.

/** The day the tests run on (src/test/setup.ts pins the clock to it). */
export const TEST_TODAY = '2026-10-18';

export const IDS = {
  di1: '6f1c2a10-0000-4000-8000-000000000001',
  di1f27: '6f1c2a10-0000-4000-8000-0000000000f7',
  di1f28: '6f1c2a10-0000-4000-8000-0000000000f8',
  di1f29: '6f1c2a10-0000-4000-8000-0000000000f9',
  di1f30: '6f1c2a10-0000-4000-8000-0000000000fa',
} as const;

const DI1_FUTURE_TYPE = { id: 1, code: 'FUTURE', name: 'Futuros' };
const INTEREST_RATE_CLASS = {
  id: 1,
  code: 'INTEREST_RATE_FUTURE',
  name: 'Futuros de Taxa de Juros',
};

export const instrumentTypes: InstrumentType[] = [
  { ...DI1_FUTURE_TYPE, asset_classes: [INTEREST_RATE_CLASS] },
];

export const products: Product[] = [
  {
    id: IDS.di1,
    code: 'DI1',
    name: 'Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia',
    asset_class: INTEREST_RATE_CLASS,
    instrument_type: DI1_FUTURE_TYPE,
    instrument_count: 4,
    futures: {
      face_value: '100000',
      contract_multiplier: '1',
      settlement_method: 'CASH',
      settlement_description: 'Liquidação financeira',
    },
    created_at: '2026-10-01T09:00:00-03:00',
  },
];

/** By maturity, as the API lists them; `last_reference` is null for now (OQ-33 item 4). */
export const instruments: Instrument[] = [
  ['DI1F27', IDS.di1f27, '2027-01-04'],
  ['DI1F28', IDS.di1f28, '2028-01-03'],
  ['DI1F29', IDS.di1f29, '2029-01-02'],
  ['DI1F30', IDS.di1f30, '2030-01-02'],
].map(([code, id, maturity]) => ({
  id: id as string,
  code: code as string,
  product_id: IDS.di1,
  product_code: 'DI1',
  maturity_date: maturity as string,
  last_reference: null,
  created_at: '2026-10-01T09:00:00-03:00',
}));

/** The trades, oldest first. */
export const tradeEntries: TradeLedgerEntry[] = [
  {
    type: 'TRADE',
    id: '7a000000-0000-4000-8000-000000000001',
    asset_id: IDS.di1f28,
    asset_code: 'DI1F28',
    instrument_type_code: 'FUTURE',
    date: '2026-10-14',
    time: '14:10:00',
    seq: 2,
    signed_quantity: 10,
    execution_pu: '89006.4625467350',
    execution_rate: '0.10',
    input_kind: 'RATE',
    cash_amount: '-890064.6254673500',
    created_at: '2026-10-14T14:11:02-03:00',
  },
  {
    type: 'TRADE',
    id: '7a000000-0000-4000-8000-000000000002',
    asset_id: IDS.di1f29,
    asset_code: 'DI1F29',
    instrument_type_code: 'FUTURE',
    date: '2026-10-15',
    time: '10:30:00',
    seq: 3,
    signed_quantity: 5,
    execution_pu: '82057.00',
    execution_rate: '0.093203413834',
    input_kind: 'PU',
    cash_amount: '-410285.00',
    created_at: '2026-10-15T10:31:40-03:00',
  },
  {
    type: 'TRADE',
    id: '7a000000-0000-4000-8000-000000000003',
    asset_id: IDS.di1f28,
    asset_code: 'DI1F28',
    instrument_type_code: 'FUTURE',
    date: '2026-10-16',
    time: '15:00:00',
    seq: 4,
    signed_quantity: -4,
    execution_pu: '89102.2226533433',
    execution_rate: '0.0995',
    input_kind: 'RATE',
    cash_amount: '356408.8906133732',
    created_at: '2026-10-16T15:02:15-03:00',
  },
];

/** Aporte: positive `cash_amount`; retirada: negative. Oldest first. */
export const cashEntries: CashLedgerEntry[] = [
  {
    type: 'CASH',
    id: '7c000000-0000-4000-8000-000000000001',
    date: '2026-10-14',
    time: '09:00:00',
    seq: 1,
    cash_amount: '1500000.00',
    created_at: '2026-10-14T09:00:00-03:00',
  },
  {
    type: 'CASH',
    id: '7c000000-0000-4000-8000-000000000002',
    date: '2026-10-16',
    time: '17:30:00',
    seq: 5,
    cash_amount: '-50000.00',
    created_at: '2026-10-16T17:30:00-03:00',
  },
];

/** Every entry, newest first by (date, time, seq), as `GET /ledger/entries` returns them. */
export const ledgerEntries: LedgerEntry[] = [
  cashEntries[1],
  tradeEntries[2],
  tradeEntries[1],
  tradeEntries[0],
  cashEntries[0],
] as LedgerEntry[];

function price(
  n: number,
  assetId: string,
  date: string,
  source: ReferencePrice['source'],
  pu: string,
  rate: string,
  createdAt = `${date}T18:00:00-03:00`,
): ReferencePrice {
  return {
    id: `7e000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
    asset_id: assetId,
    reference_date: date,
    source,
    input_kind: 'RATE',
    pu,
    rate,
    created_at: createdAt,
  };
}

/** A day with one observation, which is also the preferred one. */
const single = (observation: ReferencePrice): ReferencePriceDay => ({
  reference_date: observation.reference_date,
  preferred: observation,
  sources: [observation],
});

export const PRICES = {
  f28_1015_b3: price(7, IDS.di1f28, '2026-10-15', 'B3', '89128.4824345118', '0.0990'),
  // Corrected on 17/10, after 16/10 was processed with 89.200,9008841512 (OQ-31).
  f28_1016_manual: price(
    8,
    IDS.di1f28,
    '2026-10-16',
    'MANUAL',
    '89250.3147019396',
    '0.0980',
    '2026-10-17T10:00:00-03:00',
  ),
  f28_1016_b3: price(10, IDS.di1f28, '2026-10-16', 'B3', '89240.4279488087', '0.0981'),
} as const;

/**
 * `GET /reference-prices` per asset: the days with an observation, newest first. MANUAL is the
 * preferred observation of 16/10 (§5). No gap is filled: no carry-forward.
 */
export const referencePriceDays: Record<string, ReferencePriceDay[]> = {
  [IDS.di1f28]: [
    {
      reference_date: '2026-10-16',
      preferred: PRICES.f28_1016_manual,
      sources: [PRICES.f28_1016_manual, PRICES.f28_1016_b3],
    },
    single(PRICES.f28_1015_b3),
    single(price(6, IDS.di1f28, '2026-10-14', 'MANUAL', '89006.4625467350', '0.10')),
    single(price(5, IDS.di1f28, '2026-10-09', 'MANUAL', '88910.3037976557', '0.0998')),
    single(price(4, IDS.di1f28, '2026-10-08', 'B3', '88817.1246020680', '0.1005')),
    single(price(3, IDS.di1f28, '2026-10-05', 'MANUAL', '88777.4109547747', '0.1002')),
    single(price(2, IDS.di1f28, '2026-09-30', 'MANUAL', '88509.2489449811', '0.1017')),
    single(price(1, IDS.di1f28, '2026-09-24', 'B3', '88215.0712246655', '0.1032')),
  ],
  [IDS.di1f29]: [
    single(price(11, IDS.di1f29, '2026-10-15', 'MANUAL', '80206.1333187932', '0.1045')),
  ],
};

const PUBLISHED_AT = '2026-10-16T18:40:00-03:00';

/** `GET /portfolio/summary` for each processed date. */
export const summaries: Record<string, PortfolioSummary> = {
  '2026-10-14': {
    date: '2026-10-14',
    cash: {
      status: 'PROCESSED',
      balance: '609935.3745326500',
      trades_cash_flow: '-890064.6254673500',
      deposits: '1500000.00',
      withdrawals: '0.00',
      published_at: PUBLISHED_AT,
    },
    positions: {
      status: 'PROCESSED',
      published_at: PUBLISHED_AT,
      market_value: '890064.6254673500',
      valuation_status: 'COMPLETE',
      position_pnl: '0',
      trades_pnl: '0.0000000000',
      daily_pnl: '0.0000000000',
      cumulative_pnl: '0.0000000000',
      pnl_status: 'COMPLETE',
    },
    aum: '1500000.0000000000',
  },
  '2026-10-15': {
    date: '2026-10-15',
    cash: {
      status: 'PROCESSED',
      balance: '199650.3745326500',
      trades_cash_flow: '-410285.00',
      deposits: '0.00',
      withdrawals: '0.00',
      published_at: PUBLISHED_AT,
    },
    positions: {
      status: 'PROCESSED',
      published_at: PUBLISHED_AT,
      market_value: '1292315.4909390840',
      valuation_status: 'COMPLETE',
      position_pnl: '1220.1988777680',
      trades_pnl: '-9254.3334060340',
      daily_pnl: '-8034.1345282660',
      cumulative_pnl: '-8034.1345282660',
      pnl_status: 'COMPLETE',
    },
    aum: '1491965.8654717340',
  },
  '2026-10-16': {
    date: '2026-10-16',
    cash: {
      status: 'PROCESSED',
      balance: '506059.2651460232',
      trades_cash_flow: '356408.8906133732',
      deposits: '0.00',
      withdrawals: '50000.00',
      published_at: PUBLISHED_AT,
    },
    positions: {
      status: 'PROCESSED_WITH_ISSUES',
      published_at: PUBLISHED_AT,
      market_value: null,
      valuation_status: 'MISSING',
      position_pnl: null,
      trades_pnl: '-394.7129232316',
      daily_pnl: null,
      cumulative_pnl: null,
      pnl_status: 'MISSING',
    },
    aum: null,
  },
};

/** A date neither chain has processed. */
export function unprocessedSummary(date: string): PortfolioSummary {
  return {
    date,
    cash: {
      status: 'NOT_PROCESSED',
      balance: null,
      trades_cash_flow: null,
      deposits: null,
      withdrawals: null,
      published_at: null,
    },
    positions: {
      status: 'NOT_PROCESSED',
      published_at: null,
      market_value: null,
      valuation_status: null,
      position_pnl: null,
      trades_pnl: null,
      daily_pnl: null,
      cumulative_pnl: null,
      pnl_status: null,
    },
    aum: null,
  };
}

type PositionRow = PortfolioPositions['items'][number];

const DI1F28_15: PositionRow = {
  asset_id: IDS.di1f28,
  asset_code: 'DI1F28',
  maturity_date: '2028-01-03',
  quantity: 10,
  average_entry_pu: '89006.4625467350',
  average_entry_rate: '0.10',
  reference_source: 'B3',
  reference_pu: '89128.4824345118',
  reference_rate: '0.0990',
  financial_total: '891284.8243451180',
  position_pnl: '1220.1988777680',
  trades_pnl: '0',
  daily_pnl: '1220.1988777680',
  valuation_status: 'COMPLETE',
  pnl_status: 'COMPLETE',
};

const DI1F29_15: PositionRow = {
  asset_id: IDS.di1f29,
  asset_code: 'DI1F29',
  maturity_date: '2029-01-02',
  quantity: 5,
  average_entry_pu: '82057.00',
  average_entry_rate: '0.093203413834',
  reference_source: 'MANUAL',
  reference_pu: '80206.1333187932',
  reference_rate: '0.1045',
  financial_total: '401030.6665939660',
  position_pnl: '0',
  trades_pnl: '-9254.3334060340',
  daily_pnl: '-9254.3334060340',
  valuation_status: 'COMPLETE',
  pnl_status: 'COMPLETE',
};

/** `GET /portfolio/positions` for each processed date. */
export const positions: Record<string, PortfolioPositions> = {
  '2026-10-14': {
    date: '2026-10-14',
    status: 'PROCESSED',
    published_at: PUBLISHED_AT,
    items: [
      {
        ...DI1F28_15,
        reference_source: 'MANUAL',
        reference_pu: '89006.4625467350',
        reference_rate: '0.10',
        financial_total: '890064.6254673500',
        position_pnl: '0',
        trades_pnl: '0.0000000000',
        daily_pnl: '0.0000000000',
      },
    ],
  },
  '2026-10-15': {
    date: '2026-10-15',
    status: 'PROCESSED',
    published_at: PUBLISHED_AT,
    items: [DI1F28_15, DI1F29_15],
  },
  '2026-10-16': {
    date: '2026-10-16',
    status: 'PROCESSED_WITH_ISSUES',
    published_at: PUBLISHED_AT,
    items: [
      {
        ...DI1F28_15,
        quantity: 6,
        // The current preferred price (OQ-30), corrected after the date was processed; the
        // figures are the processed ones, at 89.200,9008841512 (OQ-31).
        reference_source: 'MANUAL',
        reference_pu: '89250.3147019396',
        reference_rate: '0.0980',
        financial_total: '535205.4053049072',
        position_pnl: '724.1844963940',
        trades_pnl: '-394.7129232316',
        daily_pnl: '329.4715731624',
      },
      {
        // No 16/10 price: quantity and averages known, valuation and P&L null (§8.3).
        ...DI1F29_15,
        reference_source: null,
        reference_pu: null,
        reference_rate: null,
        financial_total: null,
        position_pnl: null,
        trades_pnl: '0',
        daily_pnl: null,
        valuation_status: 'MISSING',
        pnl_status: 'MISSING',
      },
    ],
  },
};

export function unprocessedPositions(date: string): PortfolioPositions {
  return { date, status: 'NOT_PROCESSED', published_at: null, items: [] };
}

/**
 * `GET /portfolio/pnl`, whatever the range: one unprocessed day, then 14/10 to 16/10.
 * `range_cumulative_pnl` is the backend's running sum from 13/10 (OQ-41).
 */
export const pnlSeries: PnlPoint[] = [
  {
    date: '2026-10-13',
    status: 'NOT_PROCESSED',
    published_at: null,
    daily_pnl: null,
    cumulative_pnl: null,
    pnl_status: null,
    range_cumulative_pnl: '0',
  },
  {
    date: '2026-10-14',
    status: 'PROCESSED',
    published_at: PUBLISHED_AT,
    daily_pnl: '0.0000000000',
    cumulative_pnl: '0.0000000000',
    pnl_status: 'COMPLETE',
    range_cumulative_pnl: '0.0000000000',
  },
  {
    date: '2026-10-15',
    status: 'PROCESSED',
    published_at: PUBLISHED_AT,
    daily_pnl: '-8034.1345282660',
    cumulative_pnl: '-8034.1345282660',
    pnl_status: 'COMPLETE',
    range_cumulative_pnl: '-8034.1345282660',
  },
  {
    date: '2026-10-16',
    status: 'PROCESSED_WITH_ISSUES',
    published_at: PUBLISHED_AT,
    daily_pnl: null,
    cumulative_pnl: null,
    pnl_status: 'MISSING',
    range_cumulative_pnl: '-8034.1345282660',
  },
];

/** A processing request; tests override what they need. */
export function job(changes: Partial<ProcessingRequest> = {}): ProcessingRequest {
  return {
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
    // No dispatcher (OQ-46 item 3): the column stays, unused.
    dispatched_at: null,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
    ...changes,
  };
}

function finished(
  id: string,
  start: string,
  end: string,
  status: ProcessingRequest['status'],
  at: string,
  changes: Partial<ProcessingRequest> = {},
): ProcessingRequest {
  return job({
    id,
    start_date: start,
    end_date: end,
    status,
    progress_date: end,
    created_at: at,
    updated_at: at,
    started_at: at,
    finished_at: at,
    ...changes,
  });
}

/** `GET /processing/requests`: five finished runs, newest first (P21). */
export const processingRequests: ProcessingRequest[] = [
  finished(
    '7f3c9a02-0000-4000-8000-000000000002',
    '2026-10-14',
    '2026-10-16',
    'COMPLETED_WITH_ISSUES',
    '2026-10-16T18:35:00-03:00',
  ),
  // Cancelled after committing 14/10 and 15/10 (OQ-23); 16/10 was not reached.
  finished(
    '7f3c9a05-0000-4000-8000-000000000005',
    '2026-10-14',
    '2026-10-16',
    'CANCELLED',
    '2026-10-16T17:20:00-03:00',
    {
      progress_date: '2026-10-15',
      cancel_requested_at: '2026-10-16T17:30:40-03:00',
      finished_at: '2026-10-16T17:31:00-03:00',
      updated_at: '2026-10-16T17:31:00-03:00',
    },
  ),
  finished(
    '7f3c9a01-0000-4000-8000-000000000001',
    '2026-10-14',
    '2026-10-15',
    'COMPLETED',
    '2026-10-15T18:00:00-03:00',
  ),
  finished(
    '7f3c9a03-0000-4000-8000-000000000003',
    '2026-10-10',
    '2026-10-12',
    'CANCELLED',
    '2026-10-14T08:30:00-03:00',
    { progress_date: null, started_at: null, cancel_requested_at: '2026-10-14T08:30:05-03:00' },
  ),
  // A technical failure on its first date, of no chain (OQ-40 item 3, OQ-44).
  finished(
    '7f3c9a04-0000-4000-8000-000000000004',
    '2026-10-01',
    '2026-10-05',
    'FAILED',
    '2026-10-14T08:00:00-03:00',
    {
      progress_date: null,
      error_code: 'PROCESSING_ERROR',
      error_message: 'Erro técnico ao processar a data.',
      failed_date: '2026-10-01',
    },
  ),
];

/**
 * `GET /processing/preview` for 14/10 to 16/10: both chains start from the zero state. Each
 * fixture is one endpoint's answer, not a consistent database: with the FAILED 01/10 run above,
 * the real backend would answer NOT_PROCESSED here (OQ-40 item 5). No screen cross-checks them.
 */
export const preview: ProcessingPreview = {
  start_date: '2026-10-14',
  end_date: '2026-10-16',
  total_days: 3,
  scope: 'ALL',
  predecessor_date: '2026-10-13',
  predecessor: { cash: 'ZERO_STATE', positions: 'ZERO_STATE' },
};

export const issues: Issue[] = [
  {
    id: '7d000000-0000-4000-8000-000000000001',
    issue_type: 'MISSING_REFERENCE_PRICE',
    asset_id: IDS.di1f29,
    asset_code: 'DI1F29',
    affected_date: '2026-10-16',
    required_price_date: '2026-10-16',
    request_id: '7f3c9a02-0000-4000-8000-000000000002',
  },
];
