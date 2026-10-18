import { Paper, SimpleGrid, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { Decimal } from '@/api/contract';
import { formatMoney, UNAVAILABLE } from '@/shared/format';
import { SignedMoney } from '@/shared/ui/SignedMoney';

export interface PortfolioKpis {
  cash_balance: Decimal | null;
  aum: Decimal | null;
  daily_pnl: Decimal | null;
  position_pnl: Decimal | null;
  trades_pnl: Decimal | null;
}

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

/** The five indicators of §11.4. Cash is a KPI, never a position row (D1). */
export function KpiGrid({ kpis }: { kpis: PortfolioKpis }) {
  return (
    <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md">
      <Kpi label="Saldo em caixa">
        <Money value={kpis.cash_balance} />
      </Kpi>
      <Kpi label="Patrimônio total">
        <Money value={kpis.aum} />
      </Kpi>
      <Kpi label="P&L diário">
        <SignedMoney value={kpis.daily_pnl} />
      </Kpi>
      <Kpi label="P&L posições">
        <SignedMoney value={kpis.position_pnl} />
      </Kpi>
      <Kpi label="P&L operações">
        <SignedMoney value={kpis.trades_pnl} />
      </Kpi>
    </SimpleGrid>
  );
}
