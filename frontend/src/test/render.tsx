import { QueryCache, QueryClient } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { createMemoryRouter, Outlet, type RouteObject, RouterProvider } from 'react-router';

import { ApiError } from '@/api/http';
import { paths } from '@/app/paths';
import { AppProviders } from '@/app/providers';
import { routes } from '@/app/routes';
import { AssetsPage } from '@/features/assets/AssetsPage';
import { ContractPage } from '@/features/assets/ContractPage';
import { ProductPage } from '@/features/assets/ProductPage';
import { LedgerPage } from '@/features/ledger/LedgerPage';
import { PortfolioPage } from '@/features/portfolio/PortfolioPage';
import { ControlCenterPage } from '@/features/processing/ControlCenterPage';
import { JobWatcher } from '@/features/processing/components/JobWatcher';

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
    // As the app's client (app/queryClient.ts), without retries.
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

interface RenderAppResult extends RenderResult {
  user: UserEvent;
  router: ReturnType<typeof createMemoryRouter>;
}

/**
 * The screens without the shell: no sidebar and no lazy loading, so a test spends its time on
 * its screen. The JobWatcher stays, as in the app: it polls the jobs and refreshes the results
 * when one ends (§10.4). Every screen is routed, so links between screens work.
 */
const screenRoutes: RouteObject[] = [
  {
    element: (
      <>
        <JobWatcher />
        <Outlet />
      </>
    ),
    children: [
      { path: paths.controlCenter, element: <ControlCenterPage /> },
      { path: paths.assets, element: <AssetsPage /> },
      { path: paths.assetProduct, element: <ProductPage /> },
      { path: paths.assetContract, element: <ContractPage /> },
      { path: paths.portfolio, element: <PortfolioPage /> },
      { path: paths.ledger, element: <LedgerPage /> },
    ],
  },
];

/** Renders the screen at `route` inside the real providers (the default for screen tests). */
export function renderRoute(route: string): RenderAppResult {
  return renderRouter(screenRoutes, route);
}

/** Renders the whole app (providers, layout, lazy routes) at `route`: shell and smoke tests. */
export function renderApp(route = '/'): RenderAppResult {
  return renderRouter(routes, route);
}

function renderRouter(table: RouteObject[], route: string): RenderAppResult {
  const queryClient = testQueryClient();
  const router = createMemoryRouter(table, { initialEntries: [route] });
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
