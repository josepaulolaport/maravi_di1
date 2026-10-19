import type { RequestHandler } from 'msw';

import { assetHandlers } from './assets';
import { ledgerHandlers } from './ledger';
import { portfolioHandlers } from './portfolio';
import { priceHandlers } from './prices';
import { processingHandlers } from './processing';

// MSW handlers for the API contract (src/api/contract). They behave like a small fake
// backend over an in-memory store (./db) seeded from ./fixtures.
export const handlers: RequestHandler[] = [
  ...assetHandlers,
  ...ledgerHandlers,
  ...priceHandlers,
  ...portfolioHandlers,
  ...processingHandlers,
];
