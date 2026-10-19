import { AppShell, Center, Loader } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { Suspense } from 'react';
import { Outlet, ScrollRestoration } from 'react-router';

import { type NavItem, Sidebar } from './Sidebar';

const SIDEBAR_COLLAPSED_KEY = 'maravi:sidebar-collapsed';

/** The app shell: sidebar and main area. The navigation comes from `app` (composition). */
export function AppLayout({ navItems }: { navItems: NavItem[] }) {
  // Remembered per browser: a viewer convenience, not application state.
  const [collapsed, setCollapsed] = useLocalStorage({
    key: SIDEBAR_COLLAPSED_KEY,
    defaultValue: false,
    getInitialValueInEffect: false,
  });

  return (
    <AppShell navbar={{ width: collapsed ? 76 : 260, breakpoint: 0 }} padding={32} miw={1024}>
      <Sidebar
        navItems={navItems}
        collapsed={collapsed}
        onToggle={() => {
          setCollapsed((value) => !value);
        }}
      />
      <AppShell.Main>
        <Suspense
          fallback={
            <Center py="xl">
              <Loader size="sm" aria-label="Carregando" />
            </Center>
          }
        >
          <Outlet />
        </Suspense>
      </AppShell.Main>
      {/* A new screen opens at its top; back and forward return to where the user was. Keyed
          by path, so a screen changing only its query (search, date, range) keeps its place. */}
      <ScrollRestoration getKey={(location) => location.pathname} />
    </AppShell>
  );
}
