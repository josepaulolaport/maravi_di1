import type { FieldError, Problem } from './contract/common';

// Contract proposal: the API is served under `/api` (configurable with VITE_API_BASE_URL),
// so the SPA's own routes never collide with API paths.
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? '/api';

/** An HTTP error from the API, carrying its RFC 9457 problem (OQ-15). */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  /** `options.cause`: the original error, e.g. the fetch rejection behind a network failure. */
  constructor(problem: Problem, options?: ErrorOptions) {
    super(problem.detail ?? problem.title, options);
    this.name = 'ApiError';
    this.status = problem.status;
    this.problem = problem;
  }

  /** Field errors keyed by field name, for forms (`errors[].field`). */
  fieldErrors(): Record<string, string> {
    const result: Record<string, string> = {};
    for (const error of this.problem.errors ?? []) {
      if (error.field && !(error.field in result)) result[error.field] = error.message;
    }
    return result;
  }

  /** Messages that belong to no field: shown on the page. */
  pageErrors(): string[] {
    const errors: FieldError[] = this.problem.errors ?? [];
    const general = errors.filter((e) => !e.field).map((e) => e.message);
    return general.length > 0 || errors.length > 0 ? general : [this.message];
  }
}

const NETWORK_PROBLEM: Problem = {
  type: 'about:blank',
  title: 'Falha de comunicação',
  status: 0,
  detail: 'Não foi possível contactar o servidor. Verifique a conexão e tente novamente.',
};

type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

export function buildUrl(
  path: string,
  query?: Record<string, QueryValue>,
  base: string = API_BASE,
): string {
  // `base` may be relative (`/api`) or absolute (`https://host/api`), with or without a
  // trailing slash; `path` always starts with one.
  const url = new URL(`${base.replace(/\/+$/, '')}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === 'object' &&
    value !== null &&
    'title' in value &&
    'status' in value &&
    typeof (value as { status: unknown }).status === 'number'
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON (e.g. a proxy error page): fall back to a generic problem below.
  }
  if (isProblem(payload)) return new ApiError(payload);
  return new ApiError({
    type: 'about:blank',
    title: 'Erro inesperado',
    status: response.status,
    detail: `O servidor respondeu com o código ${response.status}. Tente novamente.`,
  });
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const init: RequestInit = { method, headers };
  // Experiment (CI only fails with it): the AbortSignal is not passed to fetch, to test whether
  // it lets reads bypass MSW on the GitHub runner. Superseded reads then complete unused.
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(NETWORK_PROBLEM, { cause: error });
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The only way the app talks to the backend. Components never call `fetch`. */
export const http = {
  get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, { ...options, body }),
  delete: <T = void>(path: string, options?: RequestOptions) => request<T>('DELETE', path, options),
};
