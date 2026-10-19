import type { MantineColor } from '@mantine/core';

import type { DateStatus } from '@/api/contract';
import { formatDateTime } from '@/shared/format';

/**
 * A date's processing status per chain in pt-BR (OQ-23, OQ-31), for the Carteira badges and the
 * Lançamentos cash strip. The label is always shown: colour is never the only signal.
 */
export const DATE_STATUS: Record<DateStatus, { label: string; color: MantineColor }> = {
  PROCESSED: { label: 'Processado', color: 'teal' },
  PROCESSED_WITH_ISSUES: { label: 'Processado com pendências', color: 'orange' },
  RUNNING: { label: 'Processando', color: 'blue' },
  FAILED: { label: 'Erro', color: 'red' },
  NOT_PROCESSED: { label: 'Não processado', color: 'gray' },
};

/** A date that needs processing: its last attempt failed, or it was never processed. */
export const needsProcessing = (status: DateStatus) =>
  status === 'FAILED' || status === 'NOT_PROCESSED';

/** "Processado em 16/10/2026 18:40" (OQ-31), or nothing for a chain never processed. */
export const processedAt = (at: string | null): string | null =>
  at === null ? null : `Processado em ${formatDateTime(at)}`;
