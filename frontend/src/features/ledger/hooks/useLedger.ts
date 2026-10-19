import {
  useInfiniteQuery,
  useIsMutating,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { useSearchParams } from 'react-router';

import type { CreateLedgerEntryRequest, IsoDate, LedgerOrder } from '@/api/contract';
import { ledgerApi } from '@/api/endpoints';
import { invalidateAfterWrite, queryRoots } from '@/api/queryRoots';
import { addDays, isIsoDate, todayInSaoPaulo } from '@/shared/format';

import type { LedgerEntry } from '../entries';

// A key's root is the API area it reads (`@/api/queryRoots`). The cash strip's summary and the
// form's catalogue come from `@/shared/queries`, shared with Carteira and Ativos.
const ledgerKeys = {
  all: queryRoots.ledger,
  entries: (start: IsoDate, end: IsoDate, search: string, order: LedgerOrder) =>
    [...queryRoots.ledger, 'entries', start, end, search, order] as const,
  /** Mutation key of the new-entry saves, so the page knows a save is running. */
  create: () => [...queryRoots.ledger, 'create'] as const,
};

/** Days in the default range, ending today (São Paulo). */
const DEFAULT_RANGE_DAYS = 30;

interface LedgerFilters {
  start: IsoDate;
  end: IsoDate;
  search: string;
  today: IsoDate;
  /** Newest first by default; `?ordem=asc` for the oldest first. */
  order: LedgerOrder;
  setRange: (start: IsoDate, end: IsoDate) => void;
  setSearch: (search: string) => void;
  setOrder: (order: LedgerOrder) => void;
}

/**
 * The inclusive range, the search and the order live in the URL (`?inicio=&fim=&busca=&ordem=`,
 * `ledgerLinks`), so a filtered view can be linked. A missing, invalid or future end is today; a missing or
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
  const order: LedgerOrder = params.get('ordem') === 'asc' ? 'asc' : 'desc';

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
    order,
    setOrder: (next) => {
      update({ ordem: next === 'asc' ? 'asc' : '' }, true);
    },
  };
}

/** Entries per page of the list (P21); "Carregar mais" reads the next one. */
const LEDGER_PAGE_SIZE = 50;

/**
 * The list, filtered and ordered by the backend (P18), read page by page (P21); `data.items`
 * holds every page read so far. A new order is a new request, from the first page.
 */
export function useEntries(start: IsoDate, end: IsoDate, search: string, order: LedgerOrder) {
  return useInfiniteQuery({
    queryKey: ledgerKeys.entries(start, end, search, order),
    queryFn: ({ pageParam, signal }) =>
      ledgerApi.listEntries(
        {
          start_date: start,
          end_date: end,
          ...(search ? { search } : {}),
          order,
          limit: LEDGER_PAGE_SIZE,
          ...(pageParam ? { cursor: pageParam } : {}),
        },
        signal,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
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

/** Every write changes the facts behind later results (§10.4): refresh what depends on them. */
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

/** Compra, venda, aporte or retirada: `POST /ledger/entries`. */
export const useCreateEntry = () =>
  useLedgerWrite(
    (body: CreateLedgerEntryRequest) => ledgerApi.createEntry(body),
    ledgerKeys.create(),
  );

/** A new entry's save is running: the modal must stay open until its result is shown. */
export const useIsSavingEntry = () => useIsMutating({ mutationKey: ledgerKeys.create() }) > 0;

/** One or several entries, of either type, all or nothing (§6.1): `POST /ledger/entries/deletions`. */
export const useDeleteEntries = () =>
  useLedgerWrite((entries: LedgerEntry[]) =>
    ledgerApi.deleteEntries({ ids: entries.map((e) => e.id) }),
  );
