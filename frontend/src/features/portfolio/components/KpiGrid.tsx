import { Paper, SimpleGrid, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { Decimal, PortfolioSummary } from '@/api/contract';
import { formatMoney, UNAVAILABLE } from '@/shared/format';
import { SignedMoney } from '@/shared/ui/SignedMoney';

function Kpi({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Paper p="md" role="group" aria-label={label}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
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
 * The five indicators of §11.4. Cash is a KPI, never a position row (D1). No figure carries a
 * freshness badge of its own: the cash and positions chains do (DataStatus).
 */
export function KpiGrid({ summary }: { summary: PortfolioSummary }) {
  const { cash, positions, aum } = summary;
  return (
    <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md">
      <Kpi label="Saldo em caixa">
        <Money value={cash.balance} />
      </Kpi>
      <Kpi label="Patrimônio total">
        <Money value={aum.value} />
      </Kpi>
      <Kpi label="P&L diário">
        <SignedMoney value={positions.daily_pnl} />
      </Kpi>
      <Kpi label="P&L posições">
        <SignedMoney value={positions.position_pnl} />
      </Kpi>
      <Kpi label="P&L operações">
        <SignedMoney value={positions.trades_pnl} />
      </Kpi>
    </SimpleGrid>
  );
}
