import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import type { IsoDate, PortfolioSummary } from '@/api/contract';
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
const RUNNING_POLL_MS = 2_000;

const isRunning = (summary: PortfolioSummary | undefined) =>
  summary?.cash.status === 'RUNNING' || summary?.positions.status === 'RUNNING';

/**
 * The portfolio summary of a date (§11.4, OQ-21). While either chain is being processed it is
 * read again every 2 s, so a "Processando" badge turns into the result without a reload; when
 * the date is done, every portfolio read (positions, the P&L series) is refreshed too, so the
 * page never mixes two runs. Only a date already RUNNING is followed: a date whose run is still
 * queued is refreshed when it starts or when the user comes back to it.
 */
export function useSummary(date: IsoDate) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: sharedKeys.summary(date),
    queryFn: () => portfolioApi.getSummary(date),
    refetchInterval: (q) => (isRunning(q.state.data) ? RUNNING_POLL_MS : false),
  });
  // The date last seen RUNNING: only that same date leaving RUNNING means its run finished;
  // moving to another date is not a finished run, so nothing is re-read.
  const runningDate = useRef<IsoDate | null>(null);
  useEffect(() => {
    if (!query.data) return;
    const { date: seen } = query.data;
    if (isRunning(query.data)) {
      runningDate.current = seen;
    } else if (runningDate.current === seen) {
      runningDate.current = null;
      void queryClient.invalidateQueries({ queryKey: queryRoots.portfolio });
    }
  }, [query.data, queryClient]);
  return query;
}

/** The instrument types with their asset classes (the catalogue tabs, §11.2). */
export function useInstrumentTypes() {
  return useQuery({
    queryKey: sharedKeys.instrumentTypes(),
    queryFn: () => assetsApi.listInstrumentTypes(),
  });
}

/** Every product; each carries its asset class (the trade form's class filter). */
export function useAllProducts() {
  return useQuery({
    queryKey: sharedKeys.allProducts(),
    queryFn: () => assetsApi.listProducts({}),
  });
}

/** Every instrument (the trade form's contract picker). */
export function useAllInstruments() {
  return useQuery({
    queryKey: sharedKeys.allInstruments(),
    queryFn: () => assetsApi.listInstruments({}),
  });
}
