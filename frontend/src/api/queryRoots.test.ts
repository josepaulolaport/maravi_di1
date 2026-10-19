import { QueryClient } from '@tanstack/react-query';

import { invalidateAfterJobFinished, invalidateAfterWrite, queryRoots } from './queryRoots';

const keys = {
  portfolio: [...queryRoots.portfolio, 'summary', '2026-10-16'],
  ledger: [...queryRoots.ledger, 'trades', '2026-09-19', '2026-10-18'],
  prices: [...queryRoots.prices, 'calendar', 'DI1F28'],
  assets: [...queryRoots.assets, 'instruments'],
  processing: [...queryRoots.processing, 'jobs'],
};

function seededClient(): QueryClient {
  const client = new QueryClient();
  for (const key of Object.values(keys)) client.setQueryData(key, 'cached');
  client.setQueryData(['unrelated'], 'cached');
  return client;
}

function invalidated(client: QueryClient): string[] {
  return Object.entries(keys)
    .filter(([, key]) => client.getQueryState(key)?.isInvalidated)
    .map(([name]) => name)
    .sort();
}

describe('query roots and cross-feature invalidation', () => {
  it('§10.4 has one distinct root per server area', () => {
    const roots = Object.values(queryRoots).map((root) => root[0]);
    expect(new Set(roots).size).toBe(roots.length);
    expect(roots.sort()).toEqual(['assets', 'ledger', 'portfolio', 'prices', 'processing']);
  });

  it('§10.4 a ledger or price write refreshes every dependent view', async () => {
    const client = seededClient();

    await invalidateAfterWrite(client);

    expect(invalidated(client)).toEqual(['assets', 'ledger', 'portfolio', 'prices', 'processing']);
    expect(client.getQueryState(['unrelated'])?.isInvalidated).toBe(false);
  });

  it('§10.4 a job reaching a final status refreshes the portfolio and the job views only', async () => {
    const client = seededClient();

    await invalidateAfterJobFinished(client);

    expect(invalidated(client)).toEqual(['portfolio', 'processing']);
  });
});
