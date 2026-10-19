import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { ResolvedConfig } from 'vite';

import { MOCK_WORKER_FILE, withoutMockWorker } from '../../vite.config';

// The production build (Docker `web` service) runs against the real API: it ships no MSW worker.
describe('production build without the MSW worker', () => {
  let root: string;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'di1-build-'));
    mkdirSync(join(root, 'out'));
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
  });

  function runPlugin(): void {
    const plugin = withoutMockWorker();
    const config = { root, build: { outDir: 'out' } } as ResolvedConfig;
    (plugin.configResolved as (c: ResolvedConfig) => void)(config);
    (plugin.closeBundle as () => void)();
  }

  it('applies to the build only, so the dev server keeps serving the worker', () => {
    expect(withoutMockWorker().apply).toBe('build');
  });

  it('removes the worker copied from public/ and keeps the rest of the output', () => {
    writeFileSync(join(root, 'out', MOCK_WORKER_FILE), '// msw');
    writeFileSync(join(root, 'out', 'index.html'), '<!doctype html>');

    runPlugin();

    expect(existsSync(join(root, 'out', MOCK_WORKER_FILE))).toBe(false);
    expect(existsSync(join(root, 'out', 'index.html'))).toBe(true);
  });

  it('does nothing when the output has no worker', () => {
    expect(runPlugin).not.toThrow();
  });
});
