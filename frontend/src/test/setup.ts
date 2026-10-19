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
  recordMswEvents();
});

// Diagnosis for a read that reaches the real network on the CI runner only: MSW's events for
// each request of the file, printed at its end for every request MSW finished resolving
// without a mocked response (a passthrough). Requests still pending when a test ends are not
// reported.
const trails = new Map<string, { url: string; test: string | undefined; events: string[] }>();
const MSW_EVENTS = [
  'request:start',
  'request:match',
  'request:unhandled',
  'request:end',
  'response:mocked',
  'response:bypass',
  'unhandledException',
] as const;
function recordMswEvents() {
  for (const type of MSW_EVENTS) {
    server.events.on(type, ({ requestId, request }) => {
      const trail = trails.get(requestId) ?? {
        url: `${request.method} ${request.url}`,
        test: expect.getState().currentTestName,
        events: [],
      };
      trail.events.push(`${type} @${performance.now().toFixed(0)}ms`);
      trails.set(requestId, trail);
    });
  }
}

function reportUnmocked() {
  for (const trail of trails.values()) {
    const has = (type: string) => trail.events.some((event) => event.startsWith(type));
    if (has('request:end') && !has('response:mocked')) {
      console.error('MSW did not mock', trail.url, 'in', trail.test, trail.events);
    }
  }
  trails.clear();
}
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
  reportUnmocked();
  server.close();
});
