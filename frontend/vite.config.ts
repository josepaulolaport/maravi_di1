import { rmSync } from 'node:fs';
import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import { loadEnv, type Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

/** The backend `docker compose up` serves locally. */
export const DEFAULT_API_TARGET = 'http://127.0.0.1:8000';

/**
 * Dev server only: with VITE_API_MOCKS=false the app calls `/api` on its own origin, and the
 * backend sends no CORS headers, so the dev server forwards the API (and the health check) to
 * the backend. `API_PROXY_TARGET` (env or `.env.local`; not exposed to the browser) points it
 * at another backend.
 */
export function apiProxy(target?: string): Record<string, string> {
  const backend = target || DEFAULT_API_TARGET;
  return { '/api': backend, '/health': backend };
}

/** MSW's service worker, which `msw init` keeps in public/ for the dev server and Vitest. */
export const MOCK_WORKER_FILE = 'mockServiceWorker.js';

/**
 * Build only: the production app always calls the real API (main.tsx starts MSW only in dev),
 * so the copy of the MSW worker that Vite takes from public/ is removed from the output.
 */
export function withoutMockWorker(): Plugin {
  let outDir = 'dist';
  return {
    name: 'di1:without-mock-worker',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      rmSync(resolve(outDir, MOCK_WORKER_FILE), { force: true });
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), withoutMockWorker()],
  server: { proxy: apiProxy(loadEnv(mode, '.', '').API_PROXY_TARGET) },
  resolve: {
    alias: { '@': decodeURIComponent(new URL('./src', import.meta.url).pathname) },
  },
  build: {
    rolldownOptions: {
      output: {
        // Vendor code changes rarely: separate chunks stay cached across app deploys. Charts
        // (recharts and its d3 dependencies) get their own chunk, loaded only by the screens
        // that draw one; higher priority wins when a module matches several groups.
        codeSplitting: {
          groups: [
            {
              name: 'charts',
              test: /node_modules[\\/](recharts|@mantine[\\/]charts|d3-[^\\/]+|victory-vendor|es-toolkit|decimal\.js-light|immer|reselect|@reduxjs|redux|react-redux|eventemitter3|internmap|use-sync-external-store)[\\/]/,
              priority: 20,
            },
            {
              name: 'react',
              test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/,
              priority: 10,
            },
            { name: 'mantine', test: /node_modules[\\/]@mantine[\\/]/, priority: 10 },
            { name: 'tanstack', test: /node_modules[\\/]@tanstack[\\/]/, priority: 10 },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // A failing query prints the whole page, not the first 7000 characters (Testing Library's
    // default), so a failure seen only in CI can be read from its log.
    env: { DEBUG_PRINT_LIMIT: '200000' },
  },
}));
