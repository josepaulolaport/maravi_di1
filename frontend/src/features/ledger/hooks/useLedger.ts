import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';

import type {
  CreateCashMovementRequest,
  CreateTradeRequest,
  DeleteEntriesRequest,
  IsoDate,
  LedgerOrder,
} from '@/api/contract';
import { assetsApi, ledgerApi, portfolioApi } from '@/api/endpoints';
import { invalidateAfterWrite, queryRoots } from '@/api/queryRoots';
import { addDays, isIsoDate, todayInSaoPaulo } from '@/shared/format';

import type { LedgerEntry } from '../entries';

// A key's root is the API area it reads (`@/api/queryRoots`): the cash strip reads the
// portfolio summary under the same key Carteira uses, so a finished job refreshes both.
export const ledgerKeys = {
  all: queryRoots.ledger,
  entries: (start: IsoDate, end: IsoDate, search: string, order: LedgerOrder) =>
    [...queryRoots.ledger, 'entries', start, end, search, order] as const,
  summary: (date: IsoDate) => [...queryRoots.portfolio, 'summary', date] as const,
  instruments: () => [...queryRoots.assets, 'instruments', 'all'] as const,
  products: () => [...queryRoots.assets, 'products', 'all'] as const,
  instrumentTypes: () => [...queryRoots.assets, 'instrument-types'] as const,
  /** Mutation key of the new-entry saves, so the page knows a save is running. */
  create: () => [...queryRoots.ledger, 'create'] as const,
};

/** Days in the default range, ending today (São Paulo). */
export const DEFAULT_RANGE_DAYS = 30;

export interface LedgerFilters {
  start: IsoDate;
  end: IsoDate;
  search: string;
  today: IsoDate;
  setRange: (start: IsoDate, end: IsoDate) => void;
  setSearch: (search: string) => void;
}

/**
 * The inclusive range and the search live in the URL (`?inicio=&fim=&busca=`, `ledgerLinks`),
 * so a filtered view can be linked. A missing, invalid or future end is today; a missing or
 * invalid start, or one after the end, is the end's 30-day window.
 */
export function useLedgerFilters(): LedgerFilters {
  const [params, setParams] = useSearchParams();
  const today = todayInSaoPaulo();
  const requestedEnd = params.get('fim');
  const requestedStart = params.get('inicio');
  const end = isIsoDate(requestedEnd) && requestedEnd <= today ? requestedEnd : today;
  const start =
    isIsoDate(requestedStart) && requestedStart <= end
      ? requestedStart
      : addDays(end, -(DEFAULT_RANGE_DAYS - 1));
  const search = params.get('busca') ?? '';

  const update = (changes: Record<string, string>, replace: boolean) => {
    setParams(
      (current) => {
        for (const [key, value] of Object.entries(changes)) {
          if (value) current.set(key, value);
          else current.delete(key);
        }
        return current;
      },
      { replace },
    );
  };

  return {
    start,
    end,
    search,
    today,
    setRange: (nextStart, nextEnd) => {
      update({ inicio: nextStart, fim: nextEnd }, false);
    },
    setSearch: (next) => {
      // Typing is debounced into the URL; each pause is not a history entry.
      update({ busca: next.trim() }, true);
    },
  };
}

/** The list, filtered and ordered by the backend (P18); a new order is a new request. */
export function useEntries(start: IsoDate, end: IsoDate, search: string, order: LedgerOrder) {
  return useQuery({
    queryKey: ledgerKeys.entries(start, end, search, order),
    queryFn: () =>
      ledgerApi.listEntries({
        start_date: start,
        end_date: end,
        ...(search ? { search } : {}),
        order,
      }),
    // Only a new order keeps the rows on screen while it loads; a new range or search shows
    // the loading state, so rows of another filter are never listed (or selected).
    placeholderData: (previous, previousQuery) => {
      const key = previousQuery?.queryKey;
      const sameFilter =
        key !== undefined && key[2] === start && key[3] === end && key[4] === search;
      return sameFilter ? previous : undefined;
    },
  });
}

export function useCashSummary(date: IsoDate) {
  return useQuery({
    queryKey: ledgerKeys.summary(date),
    queryFn: () => portfolioApi.getSummary(date),
  });
}

export function useInstruments() {
  return useQuery({
    queryKey: ledgerKeys.instruments(),
    queryFn: () => assetsApi.listInstruments(),
  });
}

/** Products carry the asset class of their contracts (the trade form's class filter). */
export function useProducts() {
  return useQuery({
    queryKey: ledgerKeys.products(),
    queryFn: () => assetsApi.listProducts(),
  });
}

export function useInstrumentTypes() {
  return useQuery({
    queryKey: ledgerKeys.instrumentTypes(),
    queryFn: () => assetsApi.listInstrumentTypes(),
  });
}

/** Every write marks published days stale (§10.4): refresh everything that depends on it. */
function useLedgerWrite<TVariables, TResult>(
  write: (variables: TVariables) => Promise<TResult>,
  mutationKey?: readonly unknown[],
) {
  const queryClient = useQueryClient();
  return useMutation({
    ...(mutationKey ? { mutationKey } : {}),
    mutationFn: write,
    onSuccess: () => invalidateAfterWrite(queryClient),
  });
}

export const useCreateTrade = () =>
  useLedgerWrite((body: CreateTradeRequest) => ledgerApi.createTrade(body), ledgerKeys.create());

export const useCreateCashMovement = () =>
  useLedgerWrite(
    (body: CreateCashMovementRequest) => ledgerApi.createCashMovement(body),
    ledgerKeys.create(),
  );

/** A new entry's save is running: the modal must stay open until its result is shown. */
export const useIsSavingEntry = () => useIsMutating({ mutationKey: ledgerKeys.create() }) > 0;

/** One entry: `DELETE /trades/{id}` or `DELETE /cash-movements/{id}`. */
export const useDeleteEntry = () =>
  useLedgerWrite((entry: LedgerEntry) =>
    entry.kind === 'trade'
      ? ledgerApi.deleteTrade(entry.id)
      : ledgerApi.deleteCashMovement(entry.id),
  );

/** Several entries, all or nothing (§6.1). */
export const useDeleteEntries = () =>
  useLedgerWrite((entries: LedgerEntry[]) => {
    const body: DeleteEntriesRequest = {
      trade_ids: entries.filter((e) => e.kind === 'trade').map((e) => e.id),
      cash_movement_ids: entries.filter((e) => e.kind === 'cash').map((e) => e.id),
    };
    return ledgerApi.deleteEntries(body);
  });
