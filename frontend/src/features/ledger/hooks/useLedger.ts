import {
  useInfiniteQuery,
  useIsMutating,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';

import type { CreateLedgerEntryRequest, IsoDate, LedgerOrder } from '@/api/contract';
import { ledgerApi } from '@/api/endpoints';
import { mutationKeys, paramsOf, queryKeys } from '@/api/queryKeys';
import { addDays } from '@/shared/format';
import {
  dateParam,
  enumParam,
  textParam,
  useQueryParams,
  withFallback,
} from '@/shared/url/useQueryParams';
import { useToday } from '@/shared/hooks/useToday';

import type { LedgerEntry } from '../model/entries';

/** Days in the default range, ending on its end date. */
const DEFAULT_RANGE_DAYS = 30;

const ORDERS: Record<LedgerOrder, string> = { asc: 'asc', desc: 'desc' };

/**
 * The inclusive range, the search and the order live in the URL (`?inicio=&fim=&busca=&ordem=`,
 * `ledgerLinks`), so a filtered view can be linked. A missing end is today; an invalid or future
 * one is corrected to today (a future one is reported, OQ-14). A missing start, or one after the
 * end, gives the end's 30-day window. Newest first unless `?ordem=asc`.
 */
export function useLedgerFilters() {
  const today = useToday();
  const { values, set } = useQueryParams(
    {
      inicio: dateParam({ max: today }),
      fim: withFallback(dateParam({ max: today }), today),
      busca: textParam,
      ordem: withFallback(enumParam(ORDERS), 'desc'),
    },
    (v) => ({ inicio: v.inicio !== null && v.inicio <= v.fim ? v.inicio : null }),
  );
  const end = values.fim;
  return {
    start: values.inicio ?? addDays(end, -(DEFAULT_RANGE_DAYS - 1)),
    end,
    search: values.busca,
    order: values.ordem,
    today,
    setRange: (start: IsoDate, nextEnd: IsoDate) => {
      set({ inicio: start, fim: nextEnd }, { push: true });
    },
    /** Typing is debounced into the URL; each pause is not a history entry. */
    setSearch: (search: string) => {
      set({ busca: search.trim() });
    },
    setOrder: (order: LedgerOrder) => {
      set({ ordem: order === 'desc' ? null : order });
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
    queryKey: queryKeys.ledger.entries({ start, end, search, order }),
    queryFn: ({ pageParam }) =>
      ledgerApi.listEntries({
        start_date: start,
        end_date: end,
        ...(search ? { search } : {}),
        order,
        limit: LEDGER_PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
    // Only a new order keeps the rows on screen while it loads; a new range or search shows
    // the loading state, so rows of another filter are never listed (or selected).
    placeholderData: (previous, previousQuery) => {
      const before = paramsOf(previousQuery);
      const sameFilter = before?.start === start && before.end === end && before.search === search;
      return sameFilter ? previous : undefined;
    },
  });
}

/**
 * A write changes the facts behind the pendências, the previews, the positions' reference
 * prices and the contracts' latest reference (§10.1, §10.4): every view is read again.
 */
function useLedgerWrite<TVariables, TResult>(
  write: (variables: TVariables) => Promise<TResult>,
  mutationKey?: readonly unknown[],
) {
  const queryClient = useQueryClient();
  return useMutation({
    ...(mutationKey ? { mutationKey } : {}),
    mutationFn: write,
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

/** Compra, venda, aporte or retirada: `POST /ledger/entries`. */
export const useCreateEntry = () =>
  useLedgerWrite(
    (body: CreateLedgerEntryRequest) => ledgerApi.createEntry(body),
    mutationKeys.createEntry,
  );

/** A new entry's save is running: the modal must stay open until its result is shown. */
export const useIsSavingEntry = () => useIsMutating({ mutationKey: mutationKeys.createEntry }) > 0;

/** One or several entries, of either type, all or nothing (§6.1): `POST /ledger/entries/deletions`. */
export const useDeleteEntries = () =>
  useLedgerWrite((entries: LedgerEntry[]) =>
    ledgerApi.deleteEntries({ ids: entries.map((e) => e.id) }),
  );
