import { useQuery } from '@tanstack/react-query';

import type { IsoDate, PortfolioSummary } from '@/api/contract';
import { assetsApi, portfolioApi } from '@/api/endpoints';
import { queryKeys } from '@/api/queryKeys';

// Reads more than one feature needs, under one key each, so they share a cache entry: the
// portfolio summary (Carteira, the Lançamentos cash strip) and the catalogue (Ativos, the
// Novo lançamento form).

/** How often a date being processed (`RUNNING`) is read again, as the job history is (§12). */
const RUNNING_POLL_MS = 2_000;

const isRunning = (summary: PortfolioSummary | undefined) =>
  summary?.cash.status === 'RUNNING' || summary?.positions.status === 'RUNNING';

/**
 * The portfolio summary of a date (§11.4, OQ-21). While either chain is being processed it is
 * read again every 2 s, so a "Processando" badge turns into the result without a reload. The
 * other portfolio reads (positions, the P&L series) are refreshed by the JobWatcher when the
 * run ends.
 */
export function useSummary(date: IsoDate) {
  return useQuery({
    queryKey: queryKeys.portfolio.summary(date),
    queryFn: () => portfolioApi.getSummary(date),
    refetchInterval: (q) => (isRunning(q.state.data) ? RUNNING_POLL_MS : false),
  });
}

/** The instrument types with their asset classes (the catalogue tabs, §11.2). */
export function useInstrumentTypes() {
  return useQuery({
    queryKey: queryKeys.assets.instrumentTypes(),
    queryFn: () => assetsApi.listInstrumentTypes(),
  });
}

/** Every product; each carries its asset class (the trade form's class filter). */
export function useAllProducts() {
  return useQuery({
    queryKey: queryKeys.assets.products({ instrumentType: null, search: '' }),
    queryFn: () => assetsApi.listProducts({}),
  });
}

/** Every instrument (the trade form's contract picker). */
export function useAllInstruments() {
  return useQuery({
    queryKey: queryKeys.assets.instruments({ productId: null, search: '' }),
    queryFn: () => assetsApi.listInstruments({}),
  });
}
