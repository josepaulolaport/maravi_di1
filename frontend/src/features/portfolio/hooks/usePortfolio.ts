import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { portfolioApi } from '@/api/endpoints';
import { addDays, isIsoDate, todayInSaoPaulo } from '@/shared/format';

export const portfolioKeys = {
  all: ['portfolio'] as const,
  summary: (date: IsoDate) => [...portfolioKeys.all, 'summary', date] as const,
  positions: (date: IsoDate) => [...portfolioKeys.all, 'positions', date] as const,
  pnl: (start: IsoDate, end: IsoDate) => [...portfolioKeys.all, 'pnl', start, end] as const,
};

/** Days of history in the cumulative P&L chart, ending on the selected date. */
export const CHART_DAYS = 30;

export function usePortfolioSummary(date: IsoDate) {
  return useQuery({
    queryKey: portfolioKeys.summary(date),
    queryFn: () => portfolioApi.getSummary(date),
  });
}

export function usePortfolioPositions(date: IsoDate) {
  return useQuery({
    queryKey: portfolioKeys.positions(date),
    queryFn: () => portfolioApi.getPositions(date),
  });
}

export function useCumulativePnl(date: IsoDate) {
  const start = addDays(date, -(CHART_DAYS - 1));
  const query = useQuery({
    queryKey: portfolioKeys.pnl(start, date),
    queryFn: () => portfolioApi.getPnlSeries({ start_date: start, end_date: date }),
  });
  return { ...query, start };
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
