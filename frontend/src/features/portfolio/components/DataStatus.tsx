import { Anchor, Group } from '@mantine/core';
import { Link } from 'react-router';

import type { Freshness, IsoDate, PortfolioSummary, ProcessingChain } from '@/api/contract';
import { controlCenterLinks } from '@/app/paths';
import { DATE_STATUS } from '@/shared/ui/dateStatus';
import { StatusBadge } from '@/shared/ui/StatusBadge';

// Freshness belongs to the two chains, not to single figures (user, 2026-10-18): one badge for
// the cash and one for the positions (valuation and P&L), each the date's status (OQ-23). AUM
// joins both, so it has none.

/**
 * Where a badge leads (frontend/CLAUDE.md, Carteira): a date with issues to Pendências; a date
 * being processed to the history; a stale, failed or unprocessed one to Processamentos,
 * prefilled with that date and chain. A current date needs nothing, so its badge is no link.
 */
function targetOf(date: IsoDate, chain: ProcessingChain, status: Freshness): string | null {
  switch (status) {
    case 'FRESH':
      return null;
    case 'FRESH_WITH_ISSUES':
      return controlCenterLinks.issues();
    case 'RUNNING':
      return controlCenterLinks.processing();
    default:
      return controlCenterLinks.processing({ start: date, end: date, scope: chain });
  }
}

const HINT: Record<'issues' | 'processing', string> = {
  issues: 'Ver pendências',
  processing: 'Ir para Processamentos',
};

export function DataStatus({ summary }: { summary: PortfolioSummary }) {
  const badge = (label: string, chain: ProcessingChain, status: Freshness) => {
    const text = `${label}: ${DATE_STATUS[status].label}`;
    const shown = <StatusBadge label={text} color={DATE_STATUS[status].color} />;
    const target = targetOf(summary.date, chain, status);
    if (target === null) return shown;
    const hint = status === 'FRESH_WITH_ISSUES' ? HINT.issues : HINT.processing;
    return (
      <Anchor
        component={Link}
        to={target}
        underline="never"
        title={hint}
        aria-label={`${text}. ${hint}`}
      >
        {shown}
      </Anchor>
    );
  };
  return (
    <Group gap="xs" role="group" aria-label="Situação dos dados">
      {badge('Caixa', 'CASH', summary.cash.status)}
      {badge('Posições', 'POSITIONS', summary.positions.status)}
    </Group>
  );
}
