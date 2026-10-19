import { Group } from '@mantine/core';

import type { Freshness, PortfolioSummary } from '@/api/contract';
import { DATE_STATUS } from '@/shared/ui/dateStatus';
import { StatusBadge } from '@/shared/ui/StatusBadge';

// Freshness belongs to the two chains, not to single figures (user, 2026-10-18): one badge for
// the cash and one for the positions (valuation and P&L), each the date's status (OQ-23). AUM
// joins both, so it has none.

export function DataStatus({ summary }: { summary: PortfolioSummary }) {
  const badge = (chain: string, status: Freshness) => (
    <StatusBadge
      label={`${chain}: ${DATE_STATUS[status].label}`}
      color={DATE_STATUS[status].color}
    />
  );
  return (
    <Group gap="xs" role="group" aria-label="Situação dos dados">
      {badge('Caixa', summary.cash.status)}
      {badge('Posições', summary.positions.status)}
    </Group>
  );
}
