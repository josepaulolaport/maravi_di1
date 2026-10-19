import type { QueryClient } from '@tanstack/react-query';

// The first element of every query key. A key's root is the API area of the endpoint it
// reads, not the feature that reads it: Lançamentos' cash strip reads /portfolio/summary, so
// its key is `[...queryRoots.portfolio, 'summary', date]`, the same key Carteira uses. A
// write can then refresh every view of that data without importing another feature.
export const queryRoots = {
  portfolio: ['portfolio'],
  ledger: ['ledger'],
  prices: ['prices'],
  assets: ['assets'],
  processing: ['processing'],
} as const;

type QueryRoot = (typeof queryRoots)[keyof typeof queryRoots];

function invalidate(client: QueryClient, roots: readonly QueryRoot[]): Promise<void> {
  return Promise.all(roots.map((queryKey) => client.invalidateQueries({ queryKey }))).then(
    () => undefined,
  );
}

/**
 * After a ledger or price write: the write changes the facts behind the pendências and the
 * range preview (§10.1, §10.4), the reference prices shown on positions (OQ-30), and a
 * contract's latest reference (§11.2).
 */
export function invalidateAfterWrite(client: QueryClient): Promise<void> {
  return invalidate(client, [
    queryRoots.ledger,
    queryRoots.prices,
    queryRoots.assets,
    queryRoots.portfolio,
    queryRoots.processing,
  ]);
}

/** After a job reaches a final status: published results and the job views changed (§10.4). */
export function invalidateAfterJobFinished(client: QueryClient): Promise<void> {
  return invalidate(client, [queryRoots.portfolio, queryRoots.processing]);
}
