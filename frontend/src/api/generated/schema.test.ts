import { readFile } from 'node:fs/promises';

import type { OpenAPI3 } from 'openapi-typescript';

import { generate, SCHEMA_JSON, SCHEMA_TS } from '../../../scripts/gen-api.ts';

// The API types are generated from the backend's OpenAPI (user, 2026-10-19). The backend's
// tests/architecture/test_openapi_snapshot.py keeps openapi.json equal to what the app serves;
// this keeps schema.ts equal to what openapi.json generates.

describe('generated API types', () => {
  it('§12 schema.ts is what `npm run gen:api` makes from the committed openapi.json', async () => {
    const document = JSON.parse(await readFile(SCHEMA_JSON, 'utf8')) as OpenAPI3;

    expect(await generate(document)).toBe(await readFile(SCHEMA_TS, 'utf8'));
  });
});
