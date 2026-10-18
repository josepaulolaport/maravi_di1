import * as fixtures from './fixtures';

// In-memory state of the fake backend. Mutations (POST/DELETE) change it for the session;
// tests call `resetDb()` before each test so every test starts from the fixtures.

function createDb() {
  return {
    instruments: structuredClone(fixtures.instruments),
    trades: structuredClone(fixtures.trades),
    cashMovements: structuredClone(fixtures.cashMovements),
    referencePrices: structuredClone(fixtures.referencePrices),
    requests: structuredClone(fixtures.processingRequests),
    issues: structuredClone(fixtures.issues),
    dirty: { ...fixtures.initialDirty },
    /** Published results by date (`portfolio_metrics`, `position_metrics`); jobs replace them. */
    published: {
      summaries: new Map(fixtures.summaries.map((s) => [s.date, structuredClone(s)])),
      positions: new Map(fixtures.positions.map((p) => [p.date, structuredClone(p)])),
      pnl: new Map(fixtures.pnlSeries.map((p) => [p.date, structuredClone(p)])),
    },
    /**
     * Earliest date touched by a write since the seed. From it on, the precomputed results no
     * longer match the inputs, and the fake cannot recalculate them.
     */
    changedFrom: null as string | null,

    /** Bumped by every write, like the backend's ledger/prices revisions (§10.2). */
    revision: 0,
    /** The revision each job saw when it started running. */
    startRevision: new Map<string, number>(),
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

/** Marks accounting (ledger change) or valuation (price change) dirty from `date` (§10.4). */
export function markDirty(kind: 'accounting' | 'valuation', date: string): void {
  db.revision += 1;
  if (db.changedFrom === null || date < db.changedFrom) db.changedFrom = date;
  const current = db.dirty[kind];
  if (current === null || date < current) db.dirty[kind] = date;
}

/**
 * A published date is stale when it is on or after any dirty marker. In this fake, a day
 * published after a stale or unprocessed predecessor (OQ-11) always has such a marker before
 * it, so the marker alone gives its stale flag.
 */
export function isStale(date: string): boolean {
  const markers = [db.dirty.accounting, db.dirty.valuation].filter((m): m is string => m !== null);
  return markers.some((marker) => date >= marker);
}
