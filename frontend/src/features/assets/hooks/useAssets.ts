import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';

import type { CreateInstrumentRequest } from '@/api/contract';
import { assetsApi } from '@/api/endpoints';
import { invalidateAfterWrite, queryRoots } from '@/api/queryRoots';

// Catalogue and instrument data (spec §3, §11.2). Keys live under the assets API area.
const assetKeys = {
  all: queryRoots.assets,
  products: (instrumentType: string, search: string) =>
    [...assetKeys.all, 'products', { instrumentType, search }] as const,
  product: (productId: string) => [...assetKeys.all, 'product', productId] as const,
  instruments: (productId: string, search: string) =>
    [...assetKeys.all, 'instruments', { productId, search }] as const,
  instrument: (instrumentId: string) => [...assetKeys.all, 'instrument', instrumentId] as const,
};

export function useProducts(instrumentType: string | undefined, search: string) {
  return useQuery({
    queryKey: assetKeys.products(instrumentType ?? '', search),
    queryFn: () => assetsApi.listProducts({ instrument_type: instrumentType ?? '', search }),
    enabled: instrumentType !== undefined,
    // While a new search of the same type loads, its previous rows stay on screen; another
    // type shows its own loading state, never the previous type's products.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[2].instrumentType === (instrumentType ?? '') ? previous : undefined,
  });
}

export function useProduct(productId: string) {
  return useQuery({
    queryKey: assetKeys.product(productId),
    queryFn: () => assetsApi.getProduct(productId),
  });
}

export function useInstruments(productId: string, search: string) {
  return useQuery({
    queryKey: assetKeys.instruments(productId, search),
    queryFn: () => assetsApi.listInstruments({ product_id: productId, search }),
    placeholderData: keepPreviousData,
  });
}

export function useInstrument(instrumentId: string) {
  return useQuery({
    queryKey: assetKeys.instrument(instrumentId),
    queryFn: () => assetsApi.getInstrument(instrumentId),
  });
}

/** "Novo contrato": a write, so every dependent view is refreshed. */
export function useCreateInstrument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateInstrumentRequest) => assetsApi.createInstrument(body),
    onSuccess: () => invalidateAfterWrite(queryClient),
  });
}

/**
 * The catalogue's search (`?busca=`): the value the queries use, and its setter, a REPLACE
 * navigation so a search is not a history entry. The box is `SearchInput`.
 */
export function useSearchParam(): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams();
  const setSearch = (value: string) => {
    setParams(
      (current) => {
        if (value) current.set('busca', value);
        else current.delete('busca');
        return current;
      },
      { replace: true },
    );
  };
  return [params.get('busca') ?? '', setSearch];
}
