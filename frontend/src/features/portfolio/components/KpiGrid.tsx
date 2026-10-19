import { Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { CashSummary, Decimal, PortfolioSummary } from '@/api/contract';
import { formatMoney, UNAVAILABLE } from '@/shared/format';
import { SignedMoney } from '@/shared/ui/SignedMoney';

/** A money figure never breaks: its sign stays with the number (QA 2026-10-19 #2). */
const NOWRAP = { whiteSpace: 'nowrap' } as const;

function Kpi({
  label,
  children,
  detail,
}: {
  label: string;
  children: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <Paper p="md" role="group" aria-label={label}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={500} mt={4}>
        {children}
      </Text>
      {detail}
    </Paper>
  );
}

/**
 * What moved the cash on the date (OQ-21; user, 2026-10-18): the operations' cash flow, the
 * aportes and the retiradas, as the backend computed them. Nothing is summed here; a date whose
 * cash was never processed has none.
 */
function CashBreakdown({ cash }: { cash: CashSummary }) {
  if (cash.status === 'NOT_PROCESSED') return null;
  const line = (label: string, value: ReactNode) => (
    <Group justify="space-between" gap={4}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xs">{value}</Text>
    </Group>
  );
  return (
    <Stack gap={2} mt="xs" role="group" aria-label="Movimentação do caixa no dia">
      {line('Operações', <SignedMoney value={cash.trades_cash_flow} style={NOWRAP} />)}
      {line('Aportes', <Money value={cash.deposits} />)}
      {line('Retiradas', <Money value={cash.withdrawals} />)}
    </Stack>
  );
}

function Money({ value }: { value: Decimal | null }) {
  const text = formatMoney(value);
  return (
    <span title={text === UNAVAILABLE ? 'Indisponível' : undefined} style={NOWRAP}>
      {text}
    </span>
  );
}

/**
 * The five indicators of §11.4. Cash is a KPI, never a position row (D1), with the day's cash
 * movement under it. No figure carries a status badge of its own: the cash and positions
 * chains do (DataStatus).
 */
export function KpiGrid({ summary }: { summary: PortfolioSummary }) {
  const { cash, positions, aum } = summary;
  return (
    // Columns follow the content's width, not the window's (the sidebar can be open or not):
    // five in a row only from 1100px, where R$ 1.491.965,87 still fits a card; three below.
    <SimpleGrid type="container" cols={{ base: 2, '640px': 3, '1100px': 5 }} spacing="md">
      <Kpi label="Saldo em caixa" detail={<CashBreakdown cash={cash} />}>
        <Money value={cash.balance} />
      </Kpi>
      <Kpi label="Patrimônio total">
        <Money value={aum} />
      </Kpi>
      <Kpi label="P&L diário">
        <SignedMoney value={positions.daily_pnl} style={NOWRAP} />
      </Kpi>
      <Kpi label="P&L posições">
        <SignedMoney value={positions.position_pnl} style={NOWRAP} />
      </Kpi>
      <Kpi label="P&L operações">
        <SignedMoney value={positions.trades_pnl} style={NOWRAP} />
      </Kpi>
    </SimpleGrid>
  );
}
