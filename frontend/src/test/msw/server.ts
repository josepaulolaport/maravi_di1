import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

import type { ProcessingRequest } from '@/api/contract';

import { handlers, problem, fieldError, url } from './handlers';

export const server = setupServer(...handlers);

/**
 * Serves the job list (and each job by id) from `jobs.items`, counting the list reads. A test
 * scripts the server by replacing `items` between polls: queued, running, finished.
 */
export function serveJobs(items: ProcessingRequest[]) {
  const jobs = { items, polls: 0 };
  server.use(
    http.get(url('/processing/requests'), () => {
      jobs.polls += 1;
      return HttpResponse.json({ items: jobs.items, next_cursor: null });
    }),
    http.get(url('/processing/requests/:id'), ({ params }) => {
      const found = jobs.items.find((j) => j.id === params.id);
      return found
        ? HttpResponse.json(found)
        : problem(404, [fieldError('NOT_FOUND', 'Processamento não encontrado.')]);
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
