import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { IsoDate, SetReferencePriceRequest } from '@/api/contract';
import { pricesApi } from '@/api/endpoints';
import { invalidateAfterWrite, queryRoots } from '@/api/queryRoots';

// Reference prices (spec §5) read and written from the contract page. Keys live under the
// prices API area, so any price write elsewhere (Pendências "Definir preço") refreshes them.
const priceKeys = {
  all: queryRoots.prices,
  days: (assetId: string, start: IsoDate, end: IsoDate) =>
    [...priceKeys.all, 'reference-prices', assetId, start, end] as const,
};

export function useReferencePriceDays(assetId: string, start: IsoDate, end: IsoDate) {
  return useQuery({
    queryKey: priceKeys.days(assetId, start, end),
    queryFn: () =>
      pricesApi.listReferencePrices({ asset_id: assetId, start_date: start, end_date: end }),
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
    onSuccess: () => invalidateAfterWrite(queryClient),
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
    onSettled: () => invalidateAfterWrite(queryClient),
  });
}
