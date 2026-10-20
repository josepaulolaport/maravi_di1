import '@testing-library/jest-dom/vitest';

import { cleanup, configure } from '@testing-library/react';

import { TEST_TODAY } from './msw/fixtures';
import { server } from './msw/server';

// A busy machine can pass the default 1 s for a `findBy*`/`waitFor` (renderApp also loads a lazy
// route); 8 s (below the 20 s test timeout in vite.config.ts) keeps them honest without masking
// real hangs.
configure({ asyncUtilTimeout: 8_000 });

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

// Tests run on the fixtures' day, whatever the real date (only Date is faked; timers stay real).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(`${TEST_TODAY}T12:00:00-03:00`));
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
