import { Group, Paper, SimpleGrid, Skeleton, Text } from '@mantine/core';

import type { IsoDate } from '@/api/contract';
import { addDays, formatDate, formatMoney, UNAVAILABLE } from '@/shared/format';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { useCashSummary } from '../hooks/useLedger';

// OQ-19 item 3, amended by OQ-21 (draft): Caixa D0 is the published cash on the range's end
// date, Caixa D−1 the one on the day before, each read from the cash chain of the portfolio
// summary with its own freshness, apart from positions. Nothing is computed from the rows.

function CashCard({ label, date }: { label: string; date: IsoDate }) {
  const summary = useCashSummary(date);

  let value: React.ReactNode;
  let marker: React.ReactNode = null;
  if (summary.isPending) {
    value = (
      <div role="status" aria-label={`Carregando ${label}`}>
        <Skeleton h={24} w={140} />
      </div>
    );
  } else if (summary.isError) {
    value = <span title="Indisponível">{UNAVAILABLE}</span>;
    marker = <StatusBadge label="Erro ao carregar" color="red" />;
  } else if (summary.data.cash.status === 'NOT_PROCESSED') {
    value = <span title="Indisponível">{UNAVAILABLE}</span>;
    marker = <StatusBadge label="Não processado" color="gray" />;
  } else {
    value = formatMoney(summary.data.cash.balance);
    if (summary.data.cash.status === 'STALE') {
      marker = <StatusBadge label="Desatualizado" color="yellow" />;
    }
  }

  return (
    <Paper p="md" role="group" aria-label={label}>
      <Group justify="space-between" gap="xs">
        <Text size="sm" c="dimmed">
          {label}
        </Text>
        <Text size="xs" c="dimmed">
          {formatDate(date)}
        </Text>
      </Group>
      <Group gap="sm" mt={4} align="center">
        <Text size="xl" fw={500} component="div">
          {value}
        </Text>
        {marker}
      </Group>
    </Paper>
  );
}

export function CashStrip({ end }: { end: IsoDate }) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
      <CashCard label="Caixa D−1" date={addDays(end, -1)} />
      <CashCard label="Caixa D0" date={end} />
    </SimpleGrid>
  );
}
