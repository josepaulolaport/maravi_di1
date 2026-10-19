import '@testing-library/jest-dom/vitest';

import { cleanup, configure } from '@testing-library/react';

import { resetDb } from '@/api/mocks/db';
import { MOCK_TODAY } from '@/api/mocks/fixtures';
import { server } from '@/api/mocks/server';

// The first test of a file also loads its lazy route, which can pass the default 1 s under a
// busy machine; 3 s keeps `findBy*`/`waitFor` honest without masking real hangs.
configure({ asyncUtilTimeout: 3_000 });

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
// jsdom does not implement it; the router's ScrollRestoration calls it on every navigation.
window.scrollTo = () => undefined;

// Every request in a test must be mocked explicitly.
beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' });
});

// Tests run on the fixture scenario's day, whatever the real date: the app and the fake
// backend both read "today" from this clock (only Date is faked; timers stay real).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(`${MOCK_TODAY}T12:00:00-03:00`));
  resetDb();
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => {
  server.close();
});
