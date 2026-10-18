import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';

import { AppProviders } from '@/app/providers';
import { createQueryClient } from '@/app/queryClient';
import { routes } from '@/app/routes';

// Until the backend serves the API, development runs against the MSW mocks.
// Set VITE_API_MOCKS=false to call a real backend instead.
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
