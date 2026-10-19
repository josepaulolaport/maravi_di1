import type { IsoDate, ProcessingScope } from '@/api/contract';
import { scopeToUrl } from '@/shared/processing/scope';

export const paths = {
  controlCenter: '/central-de-controle',
  assets: '/ativos',
  assetProduct: '/ativos/produtos/:productId',
  assetContract: '/ativos/contratos/:instrumentId',
  portfolio: '/carteira',
  ledger: '/lancamentos',
} as const;

/** Builds `path?query`, skipping empty values (URL state lives in the query string). */
function withQuery(path: string, query: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value);
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

/** Deep links into Central de Controle tabs (contextual paths from other screens, §11.4). */
export const controlCenterLinks = {
  issues: () => withQuery(paths.controlCenter, { tab: 'pendencias' }),
  /** `inicio`/`fim` and `escopo` prefill the request form; each may be given alone. */
  processing: (range?: { start?: IsoDate; end?: IsoDate; scope?: ProcessingScope }) =>
    withQuery(paths.controlCenter, {
      tab: 'processamentos',
      inicio: range?.start,
      fim: range?.end,
      escopo: range?.scope ? scopeToUrl(range.scope) : undefined,
    }),
};

/** Links into Ativos (§11.2). */
export const assetLinks = {
  catalogue: () => paths.assets,
  product: (productId: string) =>
    paths.assetProduct.replace(':productId', encodeURIComponent(productId)),
  /** `register` opens the price modal on that date ("Definir preço", §11.1). */
  contract: (instrumentId: string, options?: { register?: IsoDate }) =>
    withQuery(paths.assetContract.replace(':instrumentId', encodeURIComponent(instrumentId)), {
      registrar: options?.register,
    }),
};

/** Links into Lançamentos (§11.3): an inclusive range and a search. */
export const ledgerLinks = {
  list: (filters?: { start?: IsoDate; end?: IsoDate; search?: string }) =>
    withQuery(paths.ledger, { inicio: filters?.start, fim: filters?.end, busca: filters?.search }),
};
