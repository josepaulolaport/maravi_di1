import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';

import { resetDb } from '@/api/mocks/db';
import { server } from '@/api/mocks/server';

// jsdom lacks these browser APIs; Mantine needs them (Mantine testing guide).
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList,
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserverStub;
window.HTMLElement.prototype.scrollIntoView = () => undefined;

// Every request in a test must be mocked explicitly.
beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' });
});
beforeEach(() => {
  resetDb();
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => {
  server.close();
});
