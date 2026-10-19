import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { portfolioApi } from '@/api/endpoints';
import { queryRoots } from '@/api/queryRoots';
import { addDays, isIsoDate, todayInSaoPaulo } from '@/shared/format';

import { DEFAULT_SORT, SORT_KEYS, type Sort, type SortKey } from '../components/sortPositions';

const portfolioKeys = {
  all: queryRoots.portfolio,
  positions: (date: IsoDate) => [...portfolioKeys.all, 'positions', date] as const,
  pnl: (start: IsoDate, end: IsoDate) => [...portfolioKeys.all, 'pnl', start, end] as const,
};

/** Default days of history in the cumulative P&L chart, ending on the selected date. */
const CHART_DAYS = 30;

export function usePortfolioPositions(date: IsoDate) {
  return useQuery({
    queryKey: portfolioKeys.positions(date),
    queryFn: () => portfolioApi.getPositions(date),
  });
}

/** The cumulative P&L series for [start, date]: the chart always ends on the selected date. */
export function useCumulativePnl(start: IsoDate, date: IsoDate) {
  return useQuery({
    queryKey: portfolioKeys.pnl(start, date),
    queryFn: () => portfolioApi.getPnlSeries({ start_date: start, end_date: date }),
  });
}

/**
 * The cumulative P&L chart's first day, in the URL (`?pnl_start=YYYY-MM-DD`). It must be
 * before the selected date; otherwise (or when absent) the chart shows the CHART_DAYS days
 * ending on the date, and the invalid start is removed from the URL.
 */
export function useChartStart(date: IsoDate): [IsoDate, (start: IsoDate) => void] {
  const [params, setParams] = useSearchParams();
  const requested = params.get('pnl_start');
  const valid = isIsoDate(requested) && requested < date;
  const start = valid ? requested : addDays(date, -(CHART_DAYS - 1));
  // A start that no longer applies (the date moved before it, or a bad link) is dropped from
  // the URL, so links match the view and it never comes back when the date moves again.
  useEffect(() => {
    if (requested !== null && !valid) {
      setParams(
        (current) => {
          current.delete('pnl_start');
          return current;
        },
        { replace: true },
      );
    }
  }, [requested, valid, setParams]);
  const setStart = (next: IsoDate) => {
    setParams(
      (current) => {
        current.set('pnl_start', next);
        return current;
      },
      { replace: true },
    );
  };
  return [start, setStart];
}

/**
 * The evaluation date lives in the URL (`?date=YYYY-MM-DD`), so a Carteira view can be linked
 * and reloaded. Invalid or future dates fall back to today (São Paulo).
 */
export function useEvaluationDate(): [IsoDate, (date: IsoDate) => void, IsoDate] {
  const [params, setParams] = useSearchParams();
  const today = todayInSaoPaulo();
  const requested = params.get('date');
  const date = isIsoDate(requested) && requested <= today ? requested : today;
  // A future or invalid date in the URL is corrected there too, so links match the view.
  useEffect(() => {
    if (requested !== null && requested !== date) {
      setParams(
        (current) => {
          current.set('date', date);
          return current;
        },
        { replace: true },
      );
    }
  }, [requested, date, setParams]);
  const setDate = (next: IsoDate) => {
    setParams(
      (current) => {
        current.set('date', next);
        return current;
      },
      { replace: true },
    );
  };
  return [date, setDate, today];
}

/**
 * The positions table's search and order, in the URL (`?busca=`, `?ordem=`), so a view of
 * Carteira can be linked and reloaded. `ordem` is a column key, prefixed with `-` for
 * descending; an unknown one is the default order.
 */
export function usePositionsView() {
  const [params, setParams] = useSearchParams();
  const search = params.get('busca') ?? '';
  const raw = params.get('ordem') ?? '';
  const key = raw.replace(/^-/, '');
  const sort: Sort = SORT_KEYS.includes(key as SortKey)
    ? { key: key as SortKey, direction: raw.startsWith('-') ? 'desc' : 'asc' }
    : DEFAULT_SORT;
  const update = (name: string, value: string) => {
    setParams(
      (current) => {
        if (value) current.set(name, value);
        else current.delete(name);
        return current;
      },
      { replace: true },
    );
  };
  return {
    search,
    setSearch: (value: string) => {
      update('busca', value);
    },
    sort,
    setSort: (next: Sort) => {
      const isDefault = next.key === DEFAULT_SORT.key && next.direction === DEFAULT_SORT.direction;
      update('ordem', isDefault ? '' : `${next.direction === 'desc' ? '-' : ''}${next.key}`);
    },
  };
}
