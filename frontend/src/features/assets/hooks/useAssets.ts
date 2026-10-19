import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { NavigationType, useNavigationType, useSearchParams } from 'react-router';

import type { CreateInstrumentRequest } from '@/api/contract';
import { assetsApi } from '@/api/endpoints';
import { invalidateAfterWrite, queryRoots } from '@/api/queryRoots';

// Catalogue and instrument data (spec §3, §11.2). Keys live under the assets API area.
const assetKeys = {
  all: queryRoots.assets,
  instrumentTypes: () => [...assetKeys.all, 'instrument-types'] as const,
  products: (instrumentType: string, search: string) =>
    [...assetKeys.all, 'products', { instrumentType, search }] as const,
  product: (productId: string) => [...assetKeys.all, 'product', productId] as const,
  instruments: (productId: string, search: string) =>
    [...assetKeys.all, 'instruments', { productId, search }] as const,
  instrument: (instrumentId: string) => [...assetKeys.all, 'instrument', instrumentId] as const,
};

export function useInstrumentTypes() {
  return useQuery({
    queryKey: assetKeys.instrumentTypes(),
    queryFn: () => assetsApi.listInstrumentTypes(),
  });
}

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
 * A text search kept in the URL (`?busca=`), so a filtered view can be linked and reloaded.
 * Returns the typed text (local state, so typing is never slowed by navigation) and the
 * search in the URL, which the queries use.
 */
export function useSearchParam(): [string, (value: string) => void, string] {
  const [params, setParams] = useSearchParams();
  const search = params.get('busca') ?? '';
  const [text, setText] = useState(search);
  // The box follows the URL when navigation changes it (Back, a link). Our own updates while
  // typing are REPLACE navigations and may lag behind the text, so they never overwrite it.
  const navigationType = useNavigationType();
  const [seen, setSeen] = useState(search);
  if (seen !== search) {
    setSeen(search);
    if (navigationType !== NavigationType.Replace) setText(search);
  }
  const setSearch = (value: string) => {
    setText(value);
    setParams(
      (current) => {
        if (value) current.set('busca', value);
        else current.delete('busca');
        return current;
      },
      { replace: true },
    );
  };
  return [text, setSearch, search];
}
