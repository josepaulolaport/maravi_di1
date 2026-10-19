import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';

import { AppProviders } from '@/app/providers';
import { createQueryClient } from '@/app/queryClient';
import { routes } from '@/app/routes';

// Development runs against the MSW mocks by default. Set VITE_API_MOCKS=false to call the
// real backend through the dev server's /api proxy (vite.config.ts, API_PROXY_TARGET).
async function enableMocking(): Promise<void> {
  if (!import.meta.env.DEV || import.meta.env.VITE_API_MOCKS === 'false') return;
  const { worker } = await import('@/api/mocks/browser');
  await worker.start({ onUnhandledFrame: 'bypass' });
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Elemento #root não encontrado.');

const router = createBrowserRouter(routes);
const queryClient = createQueryClient();

void enableMocking().then(() => {
  createRoot(rootElement).render(
    <StrictMode>
      <AppProviders queryClient={queryClient}>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>,
  );
});
