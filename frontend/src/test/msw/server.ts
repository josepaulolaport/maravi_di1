import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

import type { ProcessingRequest } from '@/api/contract';

import { url } from '../helpers';

import { handlers } from './handlers';

export const server = setupServer(...handlers);

/**
 * Serves the job list from `jobs.items`, counting the list reads. A test scripts the server by
 * replacing `items` between polls: queued, running, finished. Details are read from this list.
 */
export function serveJobs(items: ProcessingRequest[]) {
  const jobs = { items, polls: 0 };
  server.use(
    http.get(url('/processing/requests'), () => {
      jobs.polls += 1;
      return HttpResponse.json({ items: jobs.items, next_cursor: null });
    }),
  );
  return jobs;
}

/** Counts the GET reads of an API path; the default handler still answers them. */
export function countReads(path: string) {
  const reads = { count: 0 };
  server.use(
    http.get(url(path), () => {
      reads.count += 1;
      return undefined;
    }),
  );
  return reads;
}

/** Records the JSON body of every POST to an API path; the default handler still answers. */
export function captureBodies(path: string) {
  const bodies: unknown[] = [];
  server.use(
    http.post(url(path), async ({ request }) => {
      bodies.push(await request.clone().json());
      return undefined;
    }),
  );
  return bodies;
}
