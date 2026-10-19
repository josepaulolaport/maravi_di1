import { QueryCache, QueryClient } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { ApiError } from '@/api/http';
import { AppProviders } from '@/app/providers';
import { routes } from '@/app/routes';

/**
 * A client for one test: no retries, and a network failure (status 0) logs the error behind it
 * with its query key, so a failure seen only on another machine (CI) can be read from its log.
 */
function testQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (error instanceof ApiError && error.status === 0) {
          console.error('Network failure in', JSON.stringify(query.queryKey), error.cause);
        }
      },
    }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

interface RenderAppResult extends RenderResult {
  user: UserEvent;
  router: ReturnType<typeof createMemoryRouter>;
}

/** Renders the whole app (providers, layout, routes) at `route`. */
export function renderApp(route = '/'): RenderAppResult {
  const queryClient = testQueryClient();
  const router = createMemoryRouter(routes, { initialEntries: [route] });
  const user = userEvent.setup();
  const result = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { user, router, ...result };
}

/**
 * Renders one component inside the real providers, without routes (for shared/ui).
 * `rerender` keeps the same providers, so a component can be given new props.
 */
export function renderUi(ui: ReactElement): RenderResult {
  const queryClient = testQueryClient();
  const wrap = (element: ReactNode) => (
    <AppProviders queryClient={queryClient}>{element}</AppProviders>
  );
  const result = render(wrap(ui));
  return {
    ...result,
    rerender: (next: ReactNode) => {
      result.rerender(wrap(next));
    },
  };
}
