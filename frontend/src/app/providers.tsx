import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/charts/styles.css';
import './global.css';
import 'dayjs/locale/pt-br';

import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { Notifications } from '@mantine/notifications';
import { type QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { cssVariablesResolver, theme } from './theme';

interface AppProvidersProps {
  children: ReactNode;
  queryClient: QueryClient;
}

export function AppProviders({ children, queryClient }: AppProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider
        theme={theme}
        cssVariablesResolver={cssVariablesResolver}
        defaultColorScheme="light"
      >
        <DatesProvider settings={{ locale: 'pt-br' }}>
          <Notifications position="bottom-center" />
          {children}
        </DatesProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}
