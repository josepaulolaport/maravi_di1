import type { IsoDate } from '@/api/contract';

export const paths = {
  controlCenter: '/central-de-controle',
  assets: '/ativos',
  portfolio: '/carteira',
  ledger: '/lancamentos',
} as const;

/** Deep links into Central de Controle tabs (contextual paths from other screens, §11.4). */
export const controlCenterLinks = {
  issues: () => `${paths.controlCenter}?tab=pendencias`,
  processing: (range?: { start: IsoDate; end: IsoDate }) =>
    range
      ? `${paths.controlCenter}?tab=processamentos&inicio=${range.start}&fim=${range.end}`
      : `${paths.controlCenter}?tab=processamentos`,
};
