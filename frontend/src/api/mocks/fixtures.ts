import type {
  CashMovement,
  Instrument,
  InstrumentType,
  Issue,
  PnlPoint,
  PortfolioPositions,
  PortfolioSummary,
  ProcessingRequest,
  Product,
  ReferencePrice,
  Trade,
} from '../contract';

// One coherent demo scenario for the MSW mocks. Every figure was computed offline with the
// spec's formulas (§4.1 DC/365, §7 accounting, §8 P&L; Decimal 34 digits, ROUND_HALF_UP,
// PU 10 dp, rate 12 dp — OQ-3), so totals match exactly: AUM = cash + market value and
// daily = position + trades P&L.
//
// Story (today = 18/10/2026):
//   14/10  Aporte 1.500.000,00; compra 10 DI1F28 a 10,00% a.a.
//   15/10  Compra 5 DI1F29 a PU 82.057,00 (B3 price for DI1F28)
//   16/10  Venda 4 DI1F28 a 9,95% a.a.; retirada 50.000,00
//          A job started at 17:20 is SUPERSEDED: the withdrawal was recorded at 17:30, mid-run.
//          No DI1F29 price  → Pendência, P&L incomplete (null), job COMPLETED_WITH_ISSUES.
//          DI1F28 price corrected after publication (revision 2) → 16/10 is stale.
//   17/10, 18/10  not processed (weekend; no prices).

export const MOCK_TODAY = '2026-10-18';

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

/** `last_reference` is derived from the price store by the handlers. */
export const instruments: Omit<Instrument, 'last_reference'>[] = [
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
  created_at: '2026-10-01T09:00:00-03:00',
}));

export const trades: Trade[] = [
  {
    id: '7a000000-0000-4000-8000-000000000001',
    asset_id: IDS.di1f28,
    asset_code: 'DI1F28',
    instrument_type_code: 'FUTURE',
    trade_date: '2026-10-14',
    trade_time: '14:10:00',
    seq: 1,
    signed_quantity: 10,
    execution_pu: '89006.4625467350',
    execution_rate: '0.10',
    input_kind: 'RATE',
    cash_amount: '-890064.6254673500',
    created_at: '2026-10-14T14:11:02-03:00',
  },
  {
    id: '7a000000-0000-4000-8000-000000000002',
    asset_id: IDS.di1f29,
    asset_code: 'DI1F29',
    instrument_type_code: 'FUTURE',
    trade_date: '2026-10-15',
    trade_time: '10:30:00',
    seq: 2,
    signed_quantity: 5,
    execution_pu: '82057.00',
    execution_rate: '0.093203413834',
    input_kind: 'PU',
    cash_amount: '-410285.00',
    created_at: '2026-10-15T10:31:40-03:00',
  },
  {
    id: '7a000000-0000-4000-8000-000000000003',
    asset_id: IDS.di1f28,
    asset_code: 'DI1F28',
    instrument_type_code: 'FUTURE',
    trade_date: '2026-10-16',
    trade_time: '15:00:00',
    seq: 3,
    signed_quantity: -4,
    execution_pu: '89102.2226533433',
    execution_rate: '0.0995',
    input_kind: 'RATE',
    cash_amount: '356408.8906133732',
    created_at: '2026-10-16T15:02:15-03:00',
  },
];

export const cashMovements: CashMovement[] = [
  {
    id: '7c000000-0000-4000-8000-000000000001',
    movement_date: '2026-10-14',
    movement_type: 'DEPOSIT',
    amount: '1500000.00',
    description: 'Aporte inicial',
    created_at: '2026-10-14T09:00:00-03:00',
  },
  {
    id: '7c000000-0000-4000-8000-000000000002',
    movement_date: '2026-10-16',
    movement_type: 'WITHDRAWAL',
    amount: '50000.00',
    description: 'Retirada parcial',
    created_at: '2026-10-16T17:30:00-03:00',
  },
];

function price(
  n: number,
  assetId: string,
  date: string,
  source: ReferencePrice['source'],
  pu: string,
  rate: string,
  revision = 1,
  supersededAt: string | null = null,
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
    revision,
    created_at: createdAt,
    superseded_at: supersededAt,
  };
}

export const PRICE_IDS = {
  f28_1014: '7e000000-0000-4000-8000-000000000006',
  f28_1015: '7e000000-0000-4000-8000-000000000007',
  f28_1016_r1: '7e000000-0000-4000-8000-000000000008',
  f28_1016_r2: '7e000000-0000-4000-8000-000000000009',
  f29_1015: '7e000000-0000-4000-8000-000000000011',
} as const;

/** All revisions, current and superseded. Gaps between dates are real: no carry-forward. */
export const referencePrices: ReferencePrice[] = [
  price(1, IDS.di1f28, '2026-09-24', 'B3', '88215.0712246655', '0.1032'),
  price(2, IDS.di1f28, '2026-09-30', 'MANUAL', '88509.2489449811', '0.1017'),
  price(3, IDS.di1f28, '2026-10-05', 'MANUAL', '88777.4109547747', '0.1002'),
  price(4, IDS.di1f28, '2026-10-08', 'B3', '88817.1246020680', '0.1005'),
  price(5, IDS.di1f28, '2026-10-09', 'MANUAL', '88910.3037976557', '0.0998'),
  price(6, IDS.di1f28, '2026-10-14', 'MANUAL', '89006.4625467350', '0.10'),
  price(7, IDS.di1f28, '2026-10-15', 'B3', '89128.4824345118', '0.0990'),
  price(
    8,
    IDS.di1f28,
    '2026-10-16',
    'MANUAL',
    '89200.9008841512',
    '0.0985',
    1,
    '2026-10-17T10:00:00-03:00',
  ),
  price(
    9,
    IDS.di1f28,
    '2026-10-16',
    'MANUAL',
    '89250.3147019396',
    '0.0980',
    2,
    null,
    '2026-10-17T10:00:00-03:00',
  ),
  price(
    10,
    IDS.di1f28,
    '2026-10-16',
    'B3',
    '89240.4279488087',
    '0.0981',
    1,
    null,
    '2026-10-16T19:00:00-03:00',
  ),
  price(11, IDS.di1f29, '2026-10-15', 'MANUAL', '80206.1333187932', '0.1045'),
];

/** First date with an input; the day before it is the valid zero state (OQ-11). */
export const FIRST_ENTRY_DATE = '2026-10-14';

/** Dirty markers (`processing.calculation_state`): the 16/10 price correction. */
export const initialDirty = {
  accounting: null as string | null,
  valuation: '2026-10-16' as string | null,
};

const PUBLISHED_AT = '2026-10-16T18:40:00-03:00';

type PublishedSummary = Extract<PortfolioSummary, { publication: 'PUBLISHED' }>;
type PublishedPositions = Extract<PortfolioPositions, { publication: 'PUBLISHED' }>;

/** Published `portfolio_metrics`; `stale` is set by the handlers from the dirty markers. */
export const summaries: Omit<PublishedSummary, 'stale'>[] = [
  {
    date: '2026-10-14',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    cash_balance: '609935.3745326500',
    positions_market_value: '890064.6254673500',
    aum: '1500000.0000000000',
    position_pnl: '0',
    trades_pnl: '0.0000000000',
    daily_pnl: '0.0000000000',
    cumulative_pnl: '0.0000000000',
    valuation_status: 'COMPLETE',
    pnl_status: 'COMPLETE',
  },
  {
    date: '2026-10-15',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    cash_balance: '199650.3745326500',
    positions_market_value: '1292315.4909390840',
    aum: '1491965.8654717340',
    position_pnl: '1220.1988777680',
    trades_pnl: '-9254.3334060340',
    daily_pnl: '-8034.1345282660',
    cumulative_pnl: '-8034.1345282660',
    valuation_status: 'COMPLETE',
    pnl_status: 'COMPLETE',
  },
  {
    date: '2026-10-16',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    cash_balance: '506059.2651460232',
    positions_market_value: null,
    aum: null,
    position_pnl: null,
    trades_pnl: '-394.7129232316',
    daily_pnl: null,
    cumulative_pnl: null,
    valuation_status: 'MISSING',
    pnl_status: 'MISSING',
  },
];

export const positions: Omit<PublishedPositions, 'stale'>[] = [
  {
    date: '2026-10-14',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    items: [
      {
        asset_id: IDS.di1f28,
        asset_code: 'DI1F28',
        maturity_date: '2028-01-03',
        quantity: 10,
        average_entry_pu: '89006.4625467350',
        average_entry_rate: '0.10',
        reference_price_id: PRICE_IDS.f28_1014,
        reference_source: 'MANUAL',
        reference_pu: '89006.4625467350',
        reference_rate: '0.10',
        financial_total: '890064.6254673500',
        position_pnl: '0',
        trades_pnl: '0.0000000000',
        daily_pnl: '0.0000000000',
        valuation_status: 'COMPLETE',
        pnl_status: 'COMPLETE',
      },
    ],
  },
  {
    date: '2026-10-15',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    items: [
      {
        asset_id: IDS.di1f28,
        asset_code: 'DI1F28',
        maturity_date: '2028-01-03',
        quantity: 10,
        average_entry_pu: '89006.4625467350',
        average_entry_rate: '0.10',
        reference_price_id: PRICE_IDS.f28_1015,
        reference_source: 'B3',
        reference_pu: '89128.4824345118',
        reference_rate: '0.0990',
        financial_total: '891284.8243451180',
        position_pnl: '1220.1988777680',
        trades_pnl: '0',
        daily_pnl: '1220.1988777680',
        valuation_status: 'COMPLETE',
        pnl_status: 'COMPLETE',
      },
      {
        asset_id: IDS.di1f29,
        asset_code: 'DI1F29',
        maturity_date: '2029-01-02',
        quantity: 5,
        average_entry_pu: '82057.00',
        average_entry_rate: '0.093203413834',
        reference_price_id: PRICE_IDS.f29_1015,
        reference_source: 'MANUAL',
        reference_pu: '80206.1333187932',
        reference_rate: '0.1045',
        financial_total: '401030.6665939660',
        position_pnl: '0',
        trades_pnl: '-9254.3334060340',
        daily_pnl: '-9254.3334060340',
        valuation_status: 'COMPLETE',
        pnl_status: 'COMPLETE',
      },
    ],
  },
  {
    date: '2026-10-16',
    publication: 'PUBLISHED',
    published_at: PUBLISHED_AT,
    items: [
      {
        // Published with revision 1 of the 16/10 price; revision 2 came later → stale.
        asset_id: IDS.di1f28,
        asset_code: 'DI1F28',
        maturity_date: '2028-01-03',
        quantity: 6,
        average_entry_pu: '89006.4625467350',
        average_entry_rate: '0.10',
        reference_price_id: PRICE_IDS.f28_1016_r1,
        reference_source: 'MANUAL',
        reference_pu: '89200.9008841512',
        reference_rate: '0.0985',
        financial_total: '535205.4053049072',
        position_pnl: '724.1844963940',
        trades_pnl: '-394.7129232316',
        daily_pnl: '329.4715731624',
        valuation_status: 'COMPLETE',
        pnl_status: 'COMPLETE',
      },
      {
        // No 16/10 price for DI1F29: quantity and averages known, valuation and P&L null.
        asset_id: IDS.di1f29,
        asset_code: 'DI1F29',
        maturity_date: '2029-01-02',
        quantity: 5,
        average_entry_pu: '82057.00',
        average_entry_rate: '0.093203413834',
        reference_price_id: null,
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
];

/** `stale` is set by the handlers. */
export const pnlSeries: Omit<PnlPoint, 'stale'>[] = [
  {
    date: '2026-10-14',
    daily_pnl: '0.0000000000',
    cumulative_pnl: '0.0000000000',
    pnl_status: 'COMPLETE',
  },
  {
    date: '2026-10-15',
    daily_pnl: '-8034.1345282660',
    cumulative_pnl: '-8034.1345282660',
    pnl_status: 'COMPLETE',
  },
  { date: '2026-10-16', daily_pnl: null, cumulative_pnl: null, pnl_status: 'MISSING' },
];

// What a job publishes when it processes a day of this scenario with its inputs unchanged.
// The fake backend does not calculate: these were computed offline with the same formulas
// and precision as the published fixtures above (re-checked: the 16/10 revision-1 figures
// reproduce exactly). 14/10 and 15/10 republish as they are; days before FIRST_ENTRY_DATE
// are the zero state (§7).

const DI1F28_AVERAGES = { average_entry_pu: '89006.4625467350', average_entry_rate: '0.10' };
const DI1F29_AVERAGES = { average_entry_pu: '82057.00', average_entry_rate: '0.093203413834' };

/** No reference price on the date: quantity and averages known, figures null (§8.3). */
function unpricedRow(
  assetId: string,
  assetCode: string,
  maturity: string,
  quantity: number,
  averages: typeof DI1F28_AVERAGES,
): PublishedPositions['items'][number] {
  return {
    asset_id: assetId,
    asset_code: assetCode,
    maturity_date: maturity,
    quantity,
    ...averages,
    reference_price_id: null,
    reference_source: null,
    reference_pu: null,
    reference_rate: null,
    financial_total: null,
    position_pnl: null,
    trades_pnl: '0',
    daily_pnl: null,
    valuation_status: 'MISSING',
    pnl_status: 'MISSING',
  };
}

/** A day after the last input (17/10, 18/10): no trades, no cash, no prices. */
function dayWithoutInputs(date: string): RecalculatedDay {
  return {
    summary: {
      date,
      publication: 'PUBLISHED',
      published_at: PUBLISHED_AT,
      cash_balance: '506059.2651460232',
      positions_market_value: null,
      aum: null,
      position_pnl: null,
      trades_pnl: '0',
      daily_pnl: null,
      cumulative_pnl: null,
      valuation_status: 'MISSING',
      pnl_status: 'MISSING',
    },
    positions: {
      date,
      publication: 'PUBLISHED',
      published_at: PUBLISHED_AT,
      items: [
        unpricedRow(IDS.di1f28, 'DI1F28', '2028-01-03', 6, DI1F28_AVERAGES),
        unpricedRow(IDS.di1f29, 'DI1F29', '2029-01-02', 5, DI1F29_AVERAGES),
      ],
    },
    pnl: { date, daily_pnl: null, cumulative_pnl: null, pnl_status: 'MISSING' },
  };
}

export interface RecalculatedDay {
  summary: Omit<PublishedSummary, 'stale'>;
  positions: Omit<PublishedPositions, 'stale'>;
  pnl: Omit<PnlPoint, 'stale'>;
}

/** Republished results that differ from the published fixtures (`published_at` is replaced). */
export const recalculatedDays: Record<string, RecalculatedDay> = {
  // DI1F28 now uses revision 2 of its 16/10 price; DI1F29 still has none, so incomplete.
  '2026-10-16': {
    summary: {
      date: '2026-10-16',
      publication: 'PUBLISHED',
      published_at: PUBLISHED_AT,
      cash_balance: '506059.2651460232',
      positions_market_value: null,
      aum: null,
      position_pnl: null,
      trades_pnl: '-592.3681943852',
      daily_pnl: null,
      cumulative_pnl: null,
      valuation_status: 'MISSING',
      pnl_status: 'MISSING',
    },
    positions: {
      date: '2026-10-16',
      publication: 'PUBLISHED',
      published_at: PUBLISHED_AT,
      items: [
        {
          asset_id: IDS.di1f28,
          asset_code: 'DI1F28',
          maturity_date: '2028-01-03',
          quantity: 6,
          ...DI1F28_AVERAGES,
          reference_price_id: PRICE_IDS.f28_1016_r2,
          reference_source: 'MANUAL',
          reference_pu: '89250.3147019396',
          reference_rate: '0.0980',
          // 6 × 89250.3147019396
          financial_total: '535501.8882116376',
          // 10 × (89250.3147019396 − 89128.4824345118)
          position_pnl: '1218.3226742780',
          // −4 × (89250.3147019396 − 89102.2226533433)
          trades_pnl: '-592.3681943852',
          daily_pnl: '625.9544798928',
          valuation_status: 'COMPLETE',
          pnl_status: 'COMPLETE',
        },
        unpricedRow(IDS.di1f29, 'DI1F29', '2029-01-02', 5, DI1F29_AVERAGES),
      ],
    },
    pnl: { date: '2026-10-16', daily_pnl: null, cumulative_pnl: null, pnl_status: 'MISSING' },
  },
  '2026-10-17': dayWithoutInputs('2026-10-17'),
  '2026-10-18': dayWithoutInputs('2026-10-18'),
};

/** A day before the first input: zero cash, no positions, zero P&L (§7). */
export function zeroStateDay(date: string): RecalculatedDay {
  return {
    summary: {
      date,
      publication: 'PUBLISHED',
      published_at: PUBLISHED_AT,
      cash_balance: '0',
      positions_market_value: '0',
      aum: '0',
      position_pnl: '0',
      trades_pnl: '0',
      daily_pnl: '0',
      cumulative_pnl: '0',
      valuation_status: 'COMPLETE',
      pnl_status: 'COMPLETE',
    },
    positions: { date, publication: 'PUBLISHED', published_at: PUBLISHED_AT, items: [] },
    pnl: { date, daily_pnl: '0', cumulative_pnl: '0', pnl_status: 'COMPLETE' },
  };
}

// Distinct in their first 8 characters, which the UI shows as the short id, as random
// UUIDs would be.
const REQUEST_IDS = {
  completed: '7f3c9a01-0000-4000-8000-000000000001',
  withIssues: '7f3c9a02-0000-4000-8000-000000000002',
  cancelled: '7f3c9a03-0000-4000-8000-000000000003',
  failed: '7f3c9a04-0000-4000-8000-000000000004',
  superseded: '7f3c9a05-0000-4000-8000-000000000005',
} as const;

function job(
  id: string,
  start: string,
  end: string,
  total: number,
  status: ProcessingRequest['status'],
  createdAt: string,
  extra: Partial<ProcessingRequest> = {},
): ProcessingRequest {
  return {
    id,
    requested_start_date: start,
    requested_end_date: end,
    status,
    created_at: createdAt,
    dispatched_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    cancel_requested_at: null,
    processed_days: total,
    total_days: total,
    progress_date: null,
    error_code: null,
    error_message: null,
    ...extra,
  };
}

/** Oldest first; the handlers return them newest first. No job is active at start. */
export const processingRequests: ProcessingRequest[] = [
  job(REQUEST_IDS.failed, '2026-10-01', '2026-10-05', 5, 'FAILED', '2026-10-14T08:00:00-03:00', {
    processed_days: 2,
    error_code: 'UNEXPECTED_ERROR',
    error_message:
      'Falha inesperada ao gravar os resultados. Nenhum dia foi publicado; tente novamente.',
  }),
  job(
    REQUEST_IDS.cancelled,
    '2026-10-10',
    '2026-10-12',
    3,
    'CANCELLED',
    '2026-10-14T08:30:00-03:00',
    {
      processed_days: 1,
      cancel_requested_at: '2026-10-14T08:30:05-03:00',
    },
  ),
  job(
    REQUEST_IDS.completed,
    '2026-10-14',
    '2026-10-15',
    2,
    'COMPLETED',
    '2026-10-15T18:00:00-03:00',
  ),
  job(
    REQUEST_IDS.superseded,
    '2026-10-14',
    '2026-10-16',
    3,
    'SUPERSEDED',
    '2026-10-16T17:20:00-03:00',
    { finished_at: '2026-10-16T17:31:00-03:00' },
  ),
  job(
    REQUEST_IDS.withIssues,
    '2026-10-14',
    '2026-10-16',
    3,
    'COMPLETED_WITH_ISSUES',
    '2026-10-16T18:35:00-03:00',
  ),
];

export const issues: Issue[] = [
  {
    id: '7d000000-0000-4000-8000-000000000001',
    issue_type: 'MISSING_REFERENCE_PRICE',
    asset_id: IDS.di1f29,
    asset_code: 'DI1F29',
    affected_date: '2026-10-16',
    required_price_date: '2026-10-16',
    request_id: REQUEST_IDS.withIssues,
  },
];
