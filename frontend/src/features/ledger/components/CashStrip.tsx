import { Button, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';

import { Loading } from '@/shared/ui/Loading';
import type { IsoDate } from '@/api/contract';
import { addDays, formatDate, formatMoney, UNAVAILABLE } from '@/shared/format';
import { DATE_STATUS, needsProcessing, processedAt } from '@/shared/ui/dateStatus';
import { useSummary } from '@/shared/queries';
import { StatusBadge } from '@/shared/ui/StatusBadge';

// OQ-19 item 3, amended by OQ-21: Caixa D0 is the published cash on the range's end
// date, Caixa D−1 the one on the day before, each read from the cash chain of the portfolio
// summary with its own status and processing time (OQ-31), apart from positions. Nothing is
// computed from the rows.

/** A day's cash needs processing when its last attempt failed or it was never processed. */
function useCashBehind(date: IsoDate): boolean {
  const status = useSummary(date).data?.cash.status;
  return status !== undefined && needsProcessing(status);
}

function CashCard({ label, date }: { label: string; date: IsoDate }) {
  const summary = useSummary(date);

  let value: React.ReactNode;
  let marker: React.ReactNode = null;
  let time: string | null = null;
  if (summary.isPending) {
    value = <Loading label={`Carregando ${label}`} h={24} w={140} />;
  } else if (summary.isError) {
    value = <span title="Indisponível">{UNAVAILABLE}</span>;
    marker = <StatusBadge label="Erro ao carregar" color="red" />;
  } else {
    // The published cash, if any (a failed date keeps what it had), with its processing time
    // (OQ-31); every status but Processado is marked.
    const status = summary.data.cash.status;
    time = processedAt(summary.data.cash.published_at);
    value =
      status === 'NOT_PROCESSED' ? (
        <span title="Indisponível">{UNAVAILABLE}</span>
      ) : (
        formatMoney(summary.data.cash.balance)
      );
    if (status !== 'PROCESSED') {
      marker = <StatusBadge label={DATE_STATUS[status].label} color={DATE_STATUS[status].color} />;
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
      {time && (
        <Text size="xs" c="dimmed" mt={2}>
          {time}
        </Text>
      )}
    </Paper>
  );
}

interface CashStripProps {
  end: IsoDate;
  /** "Processar caixa" from the first of D−1 / D0 whose cash is behind. */
  onProcessCash: (from: IsoDate) => void;
}

export function CashStrip({ end, onProcessCash }: CashStripProps) {
  const before = addDays(end, -1);
  const beforeBehind = useCashBehind(before);
  const endBehind = useCashBehind(end);
  const from = beforeBehind ? before : endBehind ? end : null;
  return (
    <Stack gap="xs">
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
        <CashCard label="Caixa D−1" date={before} />
        <CashCard label="Caixa D0" date={end} />
      </SimpleGrid>
      {from !== null && (
        <Group justify="flex-end">
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlayerPlay size={14} stroke={1.5} />}
            onClick={() => {
              onProcessCash(from);
            }}
          >
            Processar caixa
          </Button>
        </Group>
      )}
    </Stack>
  );
}
