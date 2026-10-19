import { useQuery } from '@tanstack/react-query';

import type { IsoDate } from '@/api/contract';
import { assetsApi, portfolioApi } from '@/api/endpoints';
import { queryRoots } from '@/api/queryRoots';

// Reads more than one feature needs, under one key each, so they share a cache entry: the
// portfolio summary (Carteira, the Lançamentos cash strip) and the catalogue (Ativos, the
// Novo lançamento form). A key's root is the API area it reads (`@/api/queryRoots`).

const sharedKeys = {
  summary: (date: IsoDate) => [...queryRoots.portfolio, 'summary', date] as const,
  instrumentTypes: () => [...queryRoots.assets, 'instrument-types'] as const,
  allProducts: () => [...queryRoots.assets, 'products', 'all'] as const,
  allInstruments: () => [...queryRoots.assets, 'instruments', 'all'] as const,
};

/** How often a date being processed (`RUNNING`) is read again, as the job history is (§12). */
export const RUNNING_POLL_MS = 2_000;

/**
 * The portfolio summary of a date (§11.4, OQ-21). While either chain is being processed it is
 * read again every 2 s, so a "Processando" badge turns into the result without a reload.
 */
export function useSummary(date: IsoDate) {
  return useQuery({
    queryKey: sharedKeys.summary(date),
    queryFn: ({ signal }) => portfolioApi.getSummary(date, signal),
    refetchInterval: (query) => {
      const data = query.state.data;
      const running = data?.cash.status === 'RUNNING' || data?.positions.status === 'RUNNING';
      return running ? RUNNING_POLL_MS : false;
    },
  });
}

/** The instrument types with their asset classes (the catalogue tabs, §11.2). */
export function useInstrumentTypes() {
  return useQuery({
    queryKey: sharedKeys.instrumentTypes(),
    queryFn: ({ signal }) => assetsApi.listInstrumentTypes(signal),
  });
}

/** Every product; each carries its asset class (the trade form's class filter). */
export function useAllProducts() {
  return useQuery({
    queryKey: sharedKeys.allProducts(),
    queryFn: ({ signal }) => assetsApi.listProducts({}, signal),
  });
}

/** Every instrument (the trade form's contract picker). */
export function useAllInstruments() {
  return useQuery({
    queryKey: sharedKeys.allInstruments(),
    queryFn: ({ signal }) => assetsApi.listInstruments({}, signal),
  });
}
