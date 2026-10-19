import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
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
});
