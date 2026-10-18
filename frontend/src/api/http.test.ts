import { http as mock, HttpResponse } from 'msw';

import { server } from './mocks/server';
import { API_BASE, ApiError, http } from './http';

const path = '/probe';
const url = `${API_BASE}${path}`;

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('expected the request to fail');
}

describe('http client', () => {
  it('returns the parsed JSON body and sends only non-empty query parameters', async () => {
    let seen = '';
    server.use(
      mock.get(url, ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ value: '89006.4625467350' });
      }),
    );

    const body = await http.get<{ value: string }>(path, {
      query: { date: '2026-10-15', search: '', asset_id: undefined, page: null },
    });

    expect(body).toEqual({ value: '89006.4625467350' });
    expect(seen).toBe('?date=2026-10-15');
  });

  it('sends a JSON body and returns undefined for 204', async () => {
    let received: unknown;
    server.use(
      mock.post(url, async ({ request }) => {
        received = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await expect(http.post(path, { trade_ids: ['a'] })).resolves.toBeUndefined();
    expect(received).toEqual({ trade_ids: ['a'] });
  });

  it('§12 OQ-15 turns problem+json into an ApiError with field and page messages', async () => {
    server.use(
      mock.post(url, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Dados inválidos',
            status: 422,
            detail: 'A data não pode ser posterior a hoje.',
            errors: [
              {
                code: 'FUTURE_DATE',
                message: 'A data não pode ser posterior a hoje.',
                field: 'trade_date',
              },
              { code: 'VALIDATION_ERROR', message: 'Revise os dados.', field: null },
            ],
          },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );

    const error = await captureError(http.post(path, {}));

    expect(error.status).toBe(422);
    expect(error.problem.errors?.[0]?.code).toBe('FUTURE_DATE');
    expect(error.fieldErrors()).toEqual({ trade_date: 'A data não pode ser posterior a hoje.' });
    expect(error.pageErrors()).toEqual(['Revise os dados.']);
  });

  it('uses the problem detail as the page message when there is no errors list', async () => {
    server.use(
      mock.get(url, () =>
        HttpResponse.json(
          { type: 'about:blank', title: 'Conflito', status: 409, detail: 'Já encerrado.' },
          { status: 409 },
        ),
      ),
    );

    const error = await captureError(http.get(path));

    expect(error.pageErrors()).toEqual(['Já encerrado.']);
  });

  it('gives a pt-BR problem when the error body is not problem+json', async () => {
    server.use(mock.get(url, () => new HttpResponse('<html>Bad gateway</html>', { status: 502 })));

    const error = await captureError(http.get(path));

    expect(error.status).toBe(502);
    expect(error.message).toBe('O servidor respondeu com o código 502. Tente novamente.');
  });

  it('gives a pt-BR problem when the server cannot be reached', async () => {
    server.use(mock.get(url, () => HttpResponse.error()));

    const error = await captureError(http.get(path));

    expect(error.status).toBe(0);
    expect(error.message).toBe(
      'Não foi possível contactar o servidor. Verifique a conexão e tente novamente.',
    );
  });
});
