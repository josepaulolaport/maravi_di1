import { Group } from '@mantine/core';

import type { Freshness, PortfolioSummary } from '@/api/contract';
import { StatusBadge } from '@/shared/ui/StatusBadge';

// Freshness belongs to the two chains, not to single figures (user, 2026-10-18): one badge for
// the cash and one for the positions (valuation and P&L). AUM joins both, so it has none.

const FRESHNESS: Record<Freshness, { text: string; color: string }> = {
  FRESH: { text: 'Atualizado', color: 'teal' },
  STALE: { text: 'Desatualizado', color: 'yellow' },
  NOT_PROCESSED: { text: 'Não processado', color: 'gray' },
};

export function DataStatus({ summary }: { summary: PortfolioSummary }) {
  const badge = (chain: string, status: Freshness) => (
    <StatusBadge label={`${chain}: ${FRESHNESS[status].text}`} color={FRESHNESS[status].color} />
  );
  return (
    <Group gap="xs" role="group" aria-label="Situação dos dados">
      {badge('Caixa', summary.cash.status)}
      {badge('Posições', summary.positions.status)}
    </Group>
  );
}
