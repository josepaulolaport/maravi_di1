import { Group, Paper, SimpleGrid, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { Decimal, Freshness, PortfolioSummary } from '@/api/contract';
import { formatMoney, UNAVAILABLE } from '@/shared/format';
import { SignedMoney } from '@/shared/ui/SignedMoney';
import { StatusBadge } from '@/shared/ui/StatusBadge';

/** A KPI's own freshness, from its chain (OQ-21 draft): nothing when current. */
function FreshnessMarker({ status }: { status: Freshness }) {
  if (status === 'STALE') return <StatusBadge label="Desatualizado" color="yellow" size="sm" />;
  if (status === 'NOT_PROCESSED') {
    return <StatusBadge label="Não processado" color="gray" size="sm" />;
  }
  return null;
}

function Kpi({
  label,
  status,
  children,
}: {
  label: string;
  status: Freshness;
  children: ReactNode;
}) {
  return (
    <Paper p="md" role="group" aria-label={label}>
      <Group justify="space-between" gap={4} wrap="nowrap">
        <Text size="sm" c="dimmed">
          {label}
        </Text>
        <FreshnessMarker status={status} />
      </Group>
      <Text size="xl" fw={500} mt={4}>
        {children}
      </Text>
    </Paper>
  );
}

function Money({ value }: { value: Decimal | null }) {
  const text = formatMoney(value);
  return <span title={text === UNAVAILABLE ? 'Indisponível' : undefined}>{text}</span>;
}

/**
 * The five indicators of §11.4. Cash is a KPI, never a position row (D1). Each is marked with
 * its own chain's freshness (OQ-21 draft): Saldo em caixa with the cash; the P&L with the
 * positions; Patrimônio (AUM = cash + market value) when either side is behind.
 */
export function KpiGrid({ summary }: { summary: PortfolioSummary }) {
  const { cash, positions, aum } = summary;
  return (
    <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md">
      <Kpi label="Saldo em caixa" status={cash.status}>
        <Money value={cash.balance} />
      </Kpi>
      <Kpi label="Patrimônio total" status={aum.status}>
        <Money value={aum.value} />
      </Kpi>
      <Kpi label="P&L diário" status={positions.status}>
        <SignedMoney value={positions.daily_pnl} />
      </Kpi>
      <Kpi label="P&L posições" status={positions.status}>
        <SignedMoney value={positions.position_pnl} />
      </Kpi>
      <Kpi label="P&L operações" status={positions.status}>
        <SignedMoney value={positions.trades_pnl} />
      </Kpi>
    </SimpleGrid>
  );
}
