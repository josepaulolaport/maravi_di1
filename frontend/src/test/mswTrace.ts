import { server } from '@/api/mocks/server';

// Diagnosis for reads that reach the real network on the CI runner only: MSW's lifecycle
// events for each request of a test file, so a failed read can be matched with what MSW saw
// of it (or that it saw nothing).

interface Trail {
  url: string;
  test: string | undefined;
  events: string[];
}

const trails = new Map<string, Trail>();

const MSW_EVENTS = [
  'request:start',
  'request:match',
  'request:unhandled',
  'request:end',
  'response:mocked',
  'response:bypass',
  'unhandledException',
] as const;

const now = () => `${performance.now().toFixed(0)}ms`;

/** Starts recording; call after `server.listen()`, which drops earlier listeners. */
export function recordMswEvents(): void {
  for (const type of MSW_EVENTS) {
    server.events.on(type, ({ requestId, request }) => {
      const trail = trails.get(requestId) ?? {
        url: `${request.method} ${request.url}`,
        test: expect.getState().currentTestName,
        events: [],
      };
      trail.events.push(`${type} @${now()}`);
      trails.set(requestId, trail);
    });
  }
}

/** Prints the requests MSW finished resolving without a mocked response (a passthrough). */
export function reportUnmocked(): void {
  for (const trail of trails.values()) {
    const has = (type: string) => trail.events.some((event) => event.startsWith(type));
    if (has('request:end') && !has('response:mocked')) {
      console.error('MSW did not mock', trail.url, 'in', trail.test, trail.events);
    }
  }
  trails.clear();
}

/** Prints every recorded request whose URL contains `path`, or that there is none. */
export function reportTrailsFor(path: string): void {
  const matching = [...trails.values()].filter((trail) => trail.url.includes(path));
  console.error(
    `MSW events for ${path} in this file, at ${now()}:`,
    matching.length === 0 ? 'none' : matching,
  );
}
