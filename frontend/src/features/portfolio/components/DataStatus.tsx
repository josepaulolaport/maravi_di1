import { Anchor, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';

import type { DateStatus, IsoDate, PortfolioSummary, ProcessingChain } from '@/api/contract';
import { controlCenterLinks } from '@/app/paths';
import { DATE_STATUS, processedAt } from '@/shared/ui/dateStatus';
import { StatusBadge } from '@/shared/ui/StatusBadge';

// The status belongs to the two chains, not to single figures (user, 2026-10-18): one badge for
// the cash and one for the positions (valuation and P&L), each the date's processing status and
// time (OQ-23, OQ-31). AUM joins both, so it has none.

/**
 * Where a badge leads (frontend/CLAUDE.md, Carteira): a date with issues to Pendências; a date
 * being processed to the history; a failed or unprocessed one to Processamentos, prefilled with
 * that date and chain. A processed date needs nothing, so its badge is no link.
 */
function targetOf(date: IsoDate, chain: ProcessingChain, status: DateStatus): string | null {
  switch (status) {
    case 'PROCESSED':
      return null;
    case 'PROCESSED_WITH_ISSUES':
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
  const chainStatus = (
    label: string,
    chain: ProcessingChain,
    status: DateStatus,
    at: string | null,
  ) => {
    const text = `${label}: ${DATE_STATUS[status].label}`;
    const shown = <StatusBadge label={text} color={DATE_STATUS[status].color} />;
    const target = targetOf(summary.date, chain, status);
    const hint = status === 'PROCESSED_WITH_ISSUES' ? HINT.issues : HINT.processing;
    const time = processedAt(at);
    return (
      <Stack gap={2} align="flex-end">
        {target === null ? (
          shown
        ) : (
          <Anchor
            component={Link}
            to={target}
            underline="never"
            title={hint}
            aria-label={`${text}. ${hint}`}
          >
            {shown}
          </Anchor>
        )}
        {time && (
          <Text size="xs" c="dimmed">
            {time}
          </Text>
        )}
      </Stack>
    );
  };
  return (
    <Group gap="md" align="flex-start" role="group" aria-label="Situação dos dados">
      {chainStatus('Caixa', 'CASH', summary.cash.status, summary.cash.published_at)}
      {chainStatus(
        'Posições',
        'POSITIONS',
        summary.positions.status,
        summary.positions.published_at,
      )}
    </Group>
  );
}
