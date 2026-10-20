import type { IsoDate, LedgerOrder, ProcessingScope } from './contract';

// Every query key has one shape, `[area, resource, params]`: the area is the API area the
// endpoint belongs to (not the feature that reads it), so Lançamentos' cash strip and Carteira
// share the summary of a date; `params` holds everything the request depends on. A write
// refreshes a whole area by its prefix (`queryKeys.<area>.all`).

const key = <P extends object>(area: string, resource: string, params: P) =>
  [area, resource, params] as const;

export const queryKeys = {
  assets: {
    all: ['assets'] as const,
    instrumentTypes: () => key('assets', 'instrument-types', {}),
    products: (params: { instrumentType: string | null; search: string }) =>
      key('assets', 'products', params),
    product: (id: string) => key('assets', 'product', { id }),
    instruments: (params: { productId: string | null; search: string }) =>
      key('assets', 'instruments', params),
    instrument: (id: string) => key('assets', 'instrument', { id }),
  },
  ledger: {
    all: ['ledger'] as const,
    entries: (params: { start: IsoDate; end: IsoDate; search: string; order: LedgerOrder }) =>
      key('ledger', 'entries', params),
  },
  prices: {
    all: ['prices'] as const,
    days: (params: { assetId: string; start: IsoDate; end: IsoDate } | null) =>
      key('prices', 'reference-prices', { ...params }),
  },
  portfolio: {
    all: ['portfolio'] as const,
    summary: (date: IsoDate) => key('portfolio', 'summary', { date }),
    positions: (date: IsoDate) => key('portfolio', 'positions', { date }),
    pnl: (params: { start: IsoDate; end: IsoDate }) => key('portfolio', 'pnl', params),
  },
  processing: {
    all: ['processing'] as const,
    requests: () => key('processing', 'requests', {}),
    issues: () => key('processing', 'issues', {}),
    preview: (params: { start: IsoDate; end: IsoDate; scope: ProcessingScope } | null) =>
      key('processing', 'preview', { ...params }),
  },
};

/** Mutation keys, for `useIsMutating`. */
export const mutationKeys = {
  createEntry: ['ledger', 'create-entry'] as const,
};

/**
 * The params of a query's key, for `placeholderData`: a query keeps the previous rows only when
 * the params that matter are the same, compared by name, never by key position.
 */
export const paramsOf = <P>(query: { queryKey: readonly [string, string, P] } | undefined) =>
  query?.queryKey[2];
