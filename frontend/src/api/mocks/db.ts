import type { Freshness, ProcessingChain } from '../contract';
import * as fixtures from './fixtures';

// In-memory state of the fake backend. Mutations (POST/DELETE) change it for the session;
// tests call `resetDb()` before each test so every test starts from the fixtures.
//
// Cash and positions are two chains (OQ-21). Each date has one status per chain, as in
// `processing.date_status` (OQ-23): the only source of freshness; there are no dirty markers
// and no revision counters.

type PerChain<T> = Record<ProcessingChain, T>;

/** A chain's status on a date; `null` is Não processado. */
export type ChainStatus = Exclude<Freshness, 'NOT_PROCESSED'> | null;

interface DateStatus {
  CASH: ChainStatus;
  POSITIONS: ChainStatus;
}

/**
 * The seed's statuses, as migration 0003 backfills them (OQ-23 item 11): every published date
 * FRESH, FRESH_WITH_ISSUES when its valuation or P&L is missing, STALE from the seed's stale
 * date on.
 */
function seedStatuses(): Map<string, DateStatus> {
  const statuses = new Map<string, DateStatus>();
  const staleFrom = fixtures.seedStaleFrom;
  for (const summary of fixtures.summaries) {
    const date = summary.date;
    const incomplete = summary.valuation_status === 'MISSING' || summary.pnl_status === 'MISSING';
    const at = (chain: ProcessingChain, fresh: ChainStatus): ChainStatus => {
      const from = staleFrom[chain];
      return from !== null && date >= from ? 'STALE' : fresh;
    };
    statuses.set(date, {
      CASH: at('CASH', 'FRESH'),
      POSITIONS: at('POSITIONS', incomplete ? 'FRESH_WITH_ISSUES' : 'FRESH'),
    });
  }
  return statuses;
}

function createDb() {
  return {
    instruments: structuredClone(fixtures.instruments),
    /** Trades and cash entries, one list (§6). */
    entries: structuredClone(fixtures.ledgerEntries),
    referencePrices: structuredClone(fixtures.referencePrices),
    requests: structuredClone(fixtures.processingRequests),
    issues: structuredClone(fixtures.issues),
    /** Published results by date; a run replaces each date of its scope as it commits it. */
    published: {
      /** The cash chain (`portfolio.cash_balances`). */
      cash: new Map(
        fixtures.summaries.map((s) => [
          s.date,
          {
            balance: s.cash_balance,
            trades_cash_flow: s.trades_cash_flow,
            deposits: s.deposits,
            withdrawals: s.withdrawals,
            published_at: s.published_at,
          },
        ]),
      ),
      /** The positions chain: summary figures (`portfolio_metrics`), rows and P&L series. */
      summaries: new Map(fixtures.summaries.map((s) => [s.date, structuredClone(s)])),
      positions: new Map(fixtures.positions.map((p) => [p.date, structuredClone(p)])),
      pnl: new Map(fixtures.pnlSeries.map((p) => [p.date, structuredClone(p)])),
    },
    /** `processing.date_status`: one status per date and chain (OQ-23). */
    dateStatus: seedStatuses(),
    /**
     * Per chain, the earliest date touched by a write since the seed. From it on, that chain's
     * precomputed results no longer match the inputs, and the fake cannot recalculate them.
     */
    changedFrom: { CASH: null, POSITIONS: null } as PerChain<string | null>,
    /** The statuses each run wrote, for its end: COMPLETED or COMPLETED_WITH_ISSUES. */
    written: new Map<string, ChainStatus[]>(),
    nextSeq: fixtures.ledgerEntries.length + 1,
    nextId: 1,
  };
}

export let db = createDb();

export function resetDb(): void {
  db = createDb();
}

/**
 * Deterministic ids for records created during a session, distinct in their first 8
 * characters (the short id the UI shows), as random UUIDs would be.
 */
export function newId(): string {
  const n = db.nextId++;
  // The counter is in the first block too: the history shows a job by its first 8 characters.
  return `9a${String(n).padStart(6, '0')}-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

/** A chain's status on a date (OQ-23); no status is Não processado. */
export function statusOf(date: string, chain: ProcessingChain): Freshness {
  return db.dateStatus.get(date)?.[chain] ?? 'NOT_PROCESSED';
}

/**
 * Sets a chain's status on a date. The fake never leaves a date RUNNING without committing it
 * (a cancel lets the current date commit; a failure sets it FAILED), so unlike the backend it
 * keeps no earlier status to put back (OQ-26 item 4).
 */
export function setStatus(date: string, chain: ProcessingChain, status: ChainStatus): void {
  const row = db.dateStatus.get(date) ?? { CASH: null, POSITIONS: null };
  row[chain] = status;
  db.dateStatus.set(date, row);
}

/**
 * The chains a write changes (OQ-23 item 3): a trade changes cash and positions; a cash
 * movement only cash; a reference price only positions (valuation and P&L).
 */
const CHAINS_OF_WRITE = {
  trade: ['CASH', 'POSITIONS'],
  cash: ['CASH'],
  price: ['POSITIONS'],
} as const satisfies Record<string, readonly ProcessingChain[]>;

/**
 * A write dated `date` marks its chains STALE on every date ≥ `date` that already has a
 * status, in the same step (OQ-23 item 3); dates without a status stay Não processado. A date
 * being processed stays RUNNING: its commit sets its status.
 */
export function markStale(write: keyof typeof CHAINS_OF_WRITE, date: string): void {
  for (const chain of CHAINS_OF_WRITE[write]) {
    const changed = db.changedFrom[chain];
    if (changed === null || date < changed) db.changedFrom[chain] = date;
    for (const [day, row] of db.dateStatus) {
      if (day < date || row[chain] === null || row[chain] === 'RUNNING') continue;
      row[chain] = 'STALE';
    }
  }
}

/** Whether a chain has published results for `date`. */
export function isPublished(date: string, chain: ProcessingChain): boolean {
  return chain === 'CASH' ? db.published.cash.has(date) : db.published.summaries.has(date);
}
