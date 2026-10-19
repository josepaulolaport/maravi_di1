import type { MantineColor } from '@mantine/core';

import type { Freshness } from '@/api/contract';

/**
 * A date's chain status in pt-BR (OQ-23), for the Carteira badges and the Lançamentos cash
 * strip. The label is always shown: colour is never the only signal.
 */
export const DATE_STATUS: Record<Freshness, { label: string; color: MantineColor }> = {
  FRESH: { label: 'Atualizado', color: 'teal' },
  FRESH_WITH_ISSUES: { label: 'Atualizado com pendências', color: 'orange' },
  STALE: { label: 'Desatualizado', color: 'yellow' },
  RUNNING: { label: 'Processando', color: 'blue' },
  FAILED: { label: 'Erro', color: 'red' },
  NOT_PROCESSED: { label: 'Não processado', color: 'gray' },
};

/** A date that needs processing: stale, failed, or never processed. */
export const isBehind = (status: Freshness) =>
  status === 'STALE' || status === 'FAILED' || status === 'NOT_PROCESSED';
