import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { IsoDate, ProcessingRangeRequest } from '@/api/contract';
import { processingApi } from '@/api/endpoints';
import { queryRoots } from '@/api/queryRoots';

// Requesting a processing (§10.1), shared by Central de Controle and Lançamentos.

export const processingRequestKeys = {
  preview: (range: ProcessingRangeRequest) =>
    [...queryRoots.processing, 'preview', range.start_date, range.end_date, range.scope] as const,
  outdated: (start: IsoDate, end: IsoDate) =>
    [...queryRoots.processing, 'outdated', start, end] as const,
};

/** The exact range [A, B] to process, its scope and the state before it (OQ-11, OQ-21). */
export function usePreview(range: ProcessingRangeRequest | null) {
  return useQuery({
    queryKey: range ? processingRequestKeys.preview(range) : [...queryRoots.processing, 'preview'],
    queryFn: () => processingApi.preview(range as ProcessingRangeRequest),
    enabled: range !== null,
  });
}

/** Per chain, the first stale or unprocessed day of a range (P19, OQ-21 draft). */
export function useOutdated(start: IsoDate, end: IsoDate) {
  return useQuery({
    queryKey: processingRequestKeys.outdated(start, end),
    queryFn: () => processingApi.outdated({ start_date: start, end_date: end }),
  });
}

/** Queues a job; the job views (history, Pendências, previews) refresh. */
export function useEnqueue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (range: ProcessingRangeRequest) => processingApi.enqueue(range),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryRoots.processing }),
  });
}
