import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import type { JobStatus, ProcessingRangeRequest } from '@/api/contract';
import { processingApi } from '@/api/endpoints';
import { invalidateAfterJobFinished, queryRoots } from '@/api/queryRoots';

import { isActive, isFinal } from '../jobStatus';

export const processingKeys = {
  all: queryRoots.processing,
  requests: () => [...processingKeys.all, 'requests'] as const,
  issues: () => [...processingKeys.all, 'issues'] as const,
};

/** How often the history is read while a job is active (§12). */
export const POLL_INTERVAL_MS = 2_000;

/** Jobs per page of the history (P21); "Carregar mais" reads the next one. */
export const JOBS_PAGE_SIZE = 20;

export function useIssues() {
  return useQuery({ queryKey: processingKeys.issues(), queryFn: processingApi.listIssues });
}

/**
 * The job history, newest first, read page by page (P21); `data.items` holds every page read
 * so far. It is polled only while some loaded job is queued, dispatched, running or
 * cancelling (§11.1, §12); a poll rereads the loaded pages. When a job reaches a final
 * status, the published results and the job views are refreshed once (§10.4).
 */
export function useProcessingRequests() {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: processingKeys.requests(),
    queryFn: ({ pageParam }) =>
      processingApi.listRequests({
        limit: JOBS_PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
    refetchInterval: (q) =>
      q.state.data?.pages.some((page) => page.items.some((job) => isActive(job.status)))
        ? POLL_INTERVAL_MS
        : false,
  });

  // `null` until the first load: the jobs already finished then are not news.
  const lastSeen = useRef<Map<string, JobStatus> | null>(null);
  useEffect(() => {
    const items = query.data?.items;
    if (!items) return;
    const seen = lastSeen.current;
    // A job seen active that is now final, or a new job that finished between two reads
    // (queued elsewhere, or too short to be seen running).
    const finished =
      seen !== null &&
      items.some((job) => {
        const before = seen.get(job.id);
        return isFinal(job.status) && (before === undefined || isActive(before));
      });
    lastSeen.current = new Map(items.map((job) => [job.id, job.status]));
    if (finished) void invalidateAfterJobFinished(queryClient);
  }, [query.data, queryClient]);

  return query;
}

function useProcessingMutation<TVariables, TData>(fn: (variables: TVariables) => Promise<TData>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: processingKeys.all }),
  });
}

export function useCancel() {
  return useProcessingMutation((requestId: string) => processingApi.cancel(requestId));
}

export function useCancelAndReplace() {
  return useProcessingMutation(
    ({ requestId, range }: { requestId: string; range: ProcessingRangeRequest }) =>
      processingApi.cancelAndReplace(requestId, range),
  );
}
