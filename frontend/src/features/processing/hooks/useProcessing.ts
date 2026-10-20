import {
  infiniteQueryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import type { JobStatus } from '@/api/contract';
import { processingApi } from '@/api/endpoints';
import { queryKeys } from '@/api/queryKeys';

import { isActive, isFinal } from '../model/jobStatus';

/** How often the history is read while a job is active (§12). */
const POLL_INTERVAL_MS = 2_000;

/** Jobs per page of the history (P21); "Carregar mais" reads the next one. */
const JOBS_PAGE_SIZE = 20;

export function useIssues() {
  return useQuery({
    queryKey: queryKeys.processing.issues(),
    queryFn: () => processingApi.listIssues(),
  });
}

/** The job history, newest first, read page by page (P21). One cache entry for every reader. */
const requestsQuery = infiniteQueryOptions({
  queryKey: queryKeys.processing.requests(),
  queryFn: ({ pageParam }) =>
    processingApi.listRequests({
      limit: JOBS_PAGE_SIZE,
      ...(pageParam ? { cursor: pageParam } : {}),
    }),
  initialPageParam: null as string | null,
  getNextPageParam: (page) => page.next_cursor,
});

/**
 * The job history for Central de Controle; `data.items` holds every page read so far. It does
 * not poll: `useJobWatcher`, mounted with the app shell, polls the same cache entry, so the
 * history follows a job without a second poll.
 */
export function useProcessingRequests() {
  return useInfiniteQuery({
    ...requestsQuery,
    select: (data) => ({ items: data.pages.flatMap((page) => page.items) }),
  });
}

/**
 * Follows the jobs on every screen (§10.4, §12). The history is polled only while some loaded
 * job is queued, dispatched, running or cancelling (§11.1); a poll rereads the loaded pages.
 * When a job reaches a final status, the published results and the job views are refreshed
 * once, whichever screen is open (Carteira, the Lançamentos cash strip).
 */
export function useJobWatcher(): void {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    ...requestsQuery,
    refetchInterval: (q) =>
      q.state.data?.pages.some((page) => page.items.some((job) => isActive(job.status)))
        ? POLL_INTERVAL_MS
        : false,
  });

  // `null` until the first load: the jobs already finished then are not news. `newest` is an
  // instant (ms): timestamps may carry any offset, "Z" included (#93), so they are never
  // compared as strings.
  const lastSeen = useRef<{ statuses: Map<string, JobStatus>; newest: number } | null>(null);
  useEffect(() => {
    const items = query.data?.pages.flatMap((page) => page.items);
    if (!items) return;
    const seen = lastSeen.current;
    // A job seen active that is now final, or a job newer than any seen before that is
    // already final (queued elsewhere, or too short to be seen running). An older job that
    // "Carregar mais" brings in is history, not news (P21).
    const finished =
      seen !== null &&
      items.some((job) => {
        const before = seen.statuses.get(job.id);
        if (!isFinal(job.status)) return false;
        return before === undefined ? Date.parse(job.created_at) > seen.newest : isActive(before);
      });
    const newest = items.reduce((latest, job) => {
      // An unreadable timestamp is skipped: NaN would end every later comparison.
      const created = Date.parse(job.created_at);
      return Number.isFinite(created) ? Math.max(latest, created) : latest;
    }, seen?.newest ?? Number.NEGATIVE_INFINITY);
    lastSeen.current = { statuses: new Map(items.map((job) => [job.id, job.status])), newest };
    // Published results and the job views changed (§10.4).
    if (finished) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.processing.all });
    }
  }, [query.data, queryClient]);
}

function useProcessingMutation<TVariables, TData>(fn: (variables: TVariables) => Promise<TData>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.processing.all }),
  });
}

export function useCancel() {
  return useProcessingMutation((requestId: string) => processingApi.cancel(requestId));
}
