import type { RequestHandler } from 'msw';

// MSW handlers for the draft API contract (docs/interfaces.md "HTTP endpoints").
// Each feature adds its handlers here as its screen is built.
export const handlers: RequestHandler[] = [];
