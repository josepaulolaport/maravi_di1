import type { ProcessingChain } from '../contract';
import * as fixtures from './fixtures';

// In-memory state of the fake backend. Mutations (POST/DELETE) change it for the session;
// tests call `resetDb()` before each test so every test starts from the fixtures.
//
// Cash and positions are two chains processed separately (OQ-21 draft): each has its own
// published results, dirty markers, revision and "changed since the seed" date.

type PerChain<T> = Record<ProcessingChain, T>;

function createDb() {
  return {
    instruments: structuredClone(fixtures.instruments),
    trades: structuredClone(fixtures.trades),
    cashMovements: structuredClone(fixtures.cashMovements),
    referencePrices: structuredClone(fixtures.referencePrices),
    requests: structuredClone(fixtures.processingRequests),
    issues: structuredClone(fixtures.issues),
    dirty: { ...fixtures.initialDirty },
    /** Published results by date; jobs replace the days of their scope. */
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
    /**
     * Per chain, the earliest date touched by a write since the seed. From it on, that chain's
     * precomputed results no longer match the inputs, and the fake cannot recalculate them.
     */
    changedFrom: { CASH: null, POSITIONS: null } as PerChain<string | null>,
    /** Bumped by every write to a chain's inputs, like the backend's revisions (§10.2). */
    revision: { CASH: 0, POSITIONS: 0 } as PerChain<number>,
    /** The revisions each job saw when it started running. */
    startRevision: new Map<string, PerChain<number>>(),
    nextSeq: fixtures.trades.length + 1,
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
  return `9a${String(n).padStart(6, '0')}-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

/**
 * The chains a write changes (OQ-21 draft): a trade changes cash and positions; a cash
 * movement only cash; a reference price only positions (valuation and P&L).
 */
const CHAINS_OF_WRITE = {
  trade: ['CASH', 'POSITIONS'],
  cash: ['CASH'],
  price: ['POSITIONS'],
} as const satisfies Record<string, readonly ProcessingChain[]>;

/** Marks what a write changes dirty from `date`, in the same step as the write (§10.4). */
export function markDirty(write: keyof typeof CHAINS_OF_WRITE, date: string): void {
  const earliest = (current: string | null) =>
    current === null || date < current ? date : current;
  for (const chain of CHAINS_OF_WRITE[write]) {
    db.revision[chain] += 1;
    db.changedFrom[chain] = earliest(db.changedFrom[chain]);
  }
  if (write === 'trade' || write === 'cash') db.dirty.cash = earliest(db.dirty.cash);
  if (write === 'trade') db.dirty.accounting = earliest(db.dirty.accounting);
  if (write === 'price') db.dirty.valuation = earliest(db.dirty.valuation);
}

/** The dirty markers of a chain. */
function markersOf(chain: ProcessingChain): (string | null)[] {
  return chain === 'CASH' ? [db.dirty.cash] : [db.dirty.accounting, db.dirty.valuation];
}

/**
 * A chain's published date is stale when it is on or after one of its dirty markers. A range
 * published after a stale or unprocessed day sets its chain's marker to its start (OQ-11).
 */
export function isStale(date: string, chain: ProcessingChain): boolean {
  return markersOf(chain).some((marker) => marker !== null && date >= marker);
}

/** Whether a chain has published results for `date`. */
export function isPublished(date: string, chain: ProcessingChain): boolean {
  return chain === 'CASH' ? db.published.cash.has(date) : db.published.summaries.has(date);
}
