import {
  keepPreviousData,
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import type { CreateInstrumentRequest } from '@/api/contract';
import { assetsApi } from '@/api/endpoints';
import { paramsOf, queryKeys } from '@/api/queryKeys';

// Catalogue and instrument data (spec §3, §11.2).

/** The products of an instrument type (none until the types are read), searched. */
export function useProducts(instrumentType: string | null, search: string) {
  return useQuery({
    queryKey: queryKeys.assets.products({ instrumentType, search }),
    queryFn:
      instrumentType === null
        ? skipToken
        : () => assetsApi.listProducts({ instrument_type: instrumentType, search }),
    // While a new search of the same type loads, its previous rows stay on screen; another
    // type shows its own loading state, never the previous type's products.
    placeholderData: (previous, previousQuery) =>
      paramsOf(previousQuery)?.instrumentType === instrumentType ? previous : undefined,
  });
}

export function useProduct(productId: string) {
  return useQuery({
    queryKey: queryKeys.assets.product(productId),
    queryFn: () => assetsApi.getProduct(productId),
  });
}

export function useInstruments(productId: string, search: string) {
  return useQuery({
    queryKey: queryKeys.assets.instruments({ productId, search }),
    queryFn: () => assetsApi.listInstruments({ product_id: productId, search }),
    placeholderData: keepPreviousData,
  });
}

export function useInstrument(instrumentId: string) {
  return useQuery({
    queryKey: queryKeys.assets.instrument(instrumentId),
    queryFn: () => assetsApi.getInstrument(instrumentId),
  });
}

/** "Novo contrato": a write, so every view is read again. */
export function useCreateInstrument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateInstrumentRequest) => assetsApi.createInstrument(body),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}
