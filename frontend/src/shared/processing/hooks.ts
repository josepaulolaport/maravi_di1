import { skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { ProcessingRangeRequest } from '@/api/contract';
import { processingApi } from '@/api/endpoints';
import { queryKeys } from '@/api/queryKeys';

// Requesting a processing (§10.1), shared by Central de Controle and Lançamentos.

/** The exact range [A, B] to process, its scope and the state before it (OQ-11, OQ-21). */
export function usePreview(range: ProcessingRangeRequest | null) {
  return useQuery({
    queryKey: queryKeys.processing.preview(
      range && { start: range.start_date, end: range.end_date, scope: range.scope },
    ),
    queryFn: range ? () => processingApi.preview(range) : skipToken,
  });
}

/** Queues a job; the job views (history, Pendências, previews) refresh. */
export function useEnqueue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (range: ProcessingRangeRequest) => processingApi.enqueue(range),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.processing.all }),
  });
}
