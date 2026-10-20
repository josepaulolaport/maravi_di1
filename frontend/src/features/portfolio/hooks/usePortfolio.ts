import { useQuery } from '@tanstack/react-query';

import type { IsoDate } from '@/api/contract';
import { portfolioApi } from '@/api/endpoints';
import { queryKeys } from '@/api/queryKeys';
import { addDays } from '@/shared/format';
import {
  dateParam,
  type QueryParam,
  textParam,
  useQueryParams,
  withFallback,
} from '@/shared/url/useQueryParams';
import { useToday } from '@/shared/hooks/useToday';

import { DEFAULT_SORT, SORT_KEYS, type Sort } from '../model/sortPositions';

/** Default days of history in the cumulative P&L chart, ending on the selected date. */
const CHART_DAYS = 30;

export function usePortfolioPositions(date: IsoDate) {
  return useQuery({
    queryKey: queryKeys.portfolio.positions(date),
    queryFn: () => portfolioApi.getPositions(date),
  });
}

/** The cumulative P&L series for [start, date]: the chart always ends on the selected date. */
export function useCumulativePnl(start: IsoDate, date: IsoDate) {
  return useQuery({
    queryKey: queryKeys.portfolio.pnl({ start, end: date }),
    queryFn: () => portfolioApi.getPnlSeries({ start_date: start, end_date: date }),
  });
}

/** The positions table's order in the URL: a column key, `-` first for descending. */
const sortParam: QueryParam<Sort> = {
  parse: (text) => {
    const key = text.replace(/^-/, '');
    const found = SORT_KEYS.find((k) => k === key);
    return found ? { key: found, direction: text.startsWith('-') ? 'desc' : 'asc' } : null;
  },
  format: (sort) => `${sort.direction === 'desc' ? '-' : ''}${sort.key}`,
};

const isDefaultSort = (sort: Sort) =>
  sort.key === DEFAULT_SORT.key && sort.direction === DEFAULT_SORT.direction;

/**
 * Carteira's URL state, so a view can be linked and reloaded:
 * - `?date=` the evaluation date: today when absent; an invalid or future one is corrected to
 *   today (a future one is reported, OQ-14);
 * - `?pnl_start=` the cumulative P&L chart's first day, before the date (OQ-27); otherwise the
 *   chart shows the CHART_DAYS days ending on the date, and the start leaves the URL, so it
 *   never comes back when the date moves again;
 * - `?busca=` and `?ordem=` the positions table's search and order.
 */
export function usePortfolioParams() {
  const today = useToday();
  const { values, set } = useQueryParams(
    {
      date: withFallback(dateParam({ max: today }), today),
      pnl_start: dateParam(),
      busca: textParam,
      ordem: withFallback(sortParam, DEFAULT_SORT),
    },
    (v) => ({ pnl_start: v.pnl_start !== null && v.pnl_start < v.date ? v.pnl_start : null }),
  );
  return {
    today,
    date: values.date,
    setDate: (date: IsoDate) => {
      set({ date }, { push: true });
    },
    chartStart: values.pnl_start ?? addDays(values.date, -(CHART_DAYS - 1)),
    setChartStart: (start: IsoDate) => {
      set({ pnl_start: start }, { push: true });
    },
    search: values.busca,
    setSearch: (search: string) => {
      set({ busca: search });
    },
    sort: values.ordem,
    setSort: (sort: Sort) => {
      set({ ordem: isDefaultSort(sort) ? null : sort });
    },
  };
}

export type PortfolioParams = ReturnType<typeof usePortfolioParams>;
