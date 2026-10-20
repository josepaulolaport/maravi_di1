import { skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { IsoDate, SetReferencePriceRequest } from '@/api/contract';
import { pricesApi } from '@/api/endpoints';
import { queryKeys } from '@/api/queryKeys';

// Reference prices (spec §5), read and written from Ativos. A write refreshes every view: the
// prices behind the positions, the pendências and the contracts' latest reference change too.

/** The prices of a contract's days in [start, end]; nothing is read while `days` is null. */
export function useReferencePriceDays(
  days: { assetId: string; start: IsoDate; end: IsoDate } | null,
) {
  return useQuery({
    queryKey: queryKeys.prices.days(days),
    queryFn: days
      ? () =>
          pricesApi.listReferencePrices({
            asset_id: days.assetId,
            start_date: days.start,
            end_date: days.end,
          })
      : skipToken,
  });
}

/**
 * Records the MANUAL price of a date; a correction is the same call and replaces it (OQ-26).
 * The write changes no processed result and starts no processing (§10.1, OQ-31): only the
 * views refresh.
 */
export function useSetReferencePrice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SetReferencePriceRequest) => pricesApi.setReferencePrice(body),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

/**
 * Deletes the prices the user selected, of any source (§5;
 * user decision 2026-10-18). There is no batch endpoint, so each id is one DELETE, in order;
 * the views refresh even after a partial failure, so they show what was removed.
 */
export function useRemoveReferencePrices() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (priceIds: string[]) => {
      for (const priceId of priceIds) await pricesApi.removeReferencePrice(priceId);
    },
    onSettled: () => queryClient.invalidateQueries(),
  });
}
