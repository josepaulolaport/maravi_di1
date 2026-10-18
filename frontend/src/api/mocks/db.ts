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

/** Deterministic ids for records created during a session. */
export function newId(): string {
  const n = db.nextId++;
  return `9a000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

/** Marks accounting (ledger change) or valuation (price change) dirty from `date` (§10.4). */
export function markDirty(kind: 'accounting' | 'valuation', date: string): void {
  db.revision += 1;
  const current = db.dirty[kind];
  if (current === null || date < current) db.dirty[kind] = date;
}

/** A published date is stale when it is on or after any dirty marker. */
export function isStale(date: string): boolean {
  const markers = [db.dirty.accounting, db.dirty.valuation].filter((m): m is string => m !== null);
  return markers.some((marker) => date >= marker);
}
