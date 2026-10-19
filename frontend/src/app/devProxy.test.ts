import { apiProxy, DEFAULT_API_TARGET } from '../../vite.config';

// The app calls `/api` on its own origin (the Vite dev server), and the backend sends no CORS
// headers, so the dev server forwards the API to the backend.
describe('dev-server proxy to the real backend (Wave 5)', () => {
  it('forwards /api and /health to the local backend by default', () => {
    expect(DEFAULT_API_TARGET).toBe('http://127.0.0.1:8000');
    expect(apiProxy()).toEqual({
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    });
  });

  it('takes another backend from API_PROXY_TARGET', () => {
    expect(apiProxy('http://api.local:9000')).toEqual({
      '/api': 'http://api.local:9000',
      '/health': 'http://api.local:9000',
    });
  });

  it('falls back to the default when API_PROXY_TARGET is empty', () => {
    expect(apiProxy('')).toEqual(apiProxy());
  });
});
