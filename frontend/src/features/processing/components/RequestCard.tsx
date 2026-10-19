import { Button, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';

import type { IsoDate, ProcessingScope } from '@/api/contract';
import { ScopeField } from '@/shared/processing/ScopeField';

import { isValidRange, RangeFields } from '@/shared/processing/RangeFields';

interface RequestCardProps {
  start: IsoDate | null;
  end: IsoDate | null;
  onStartChange: (date: IsoDate | null) => void;
  onEndChange: (date: IsoDate | null) => void;
  scope: ProcessingScope;
  onScopeChange: (scope: ProcessingScope) => void;
  today: IsoDate;
  onRequest: () => void;
}

/**
 * "Solicitar processamento" (§10.1): an inclusive range and its scope (OQ-21: Caixa,
 * Posições or Tudo), previewed before it is queued.
 */
export function RequestCard({
  start,
  end,
  onStartChange,
  onEndChange,
  scope,
  onScopeChange,
  today,
  onRequest,
}: RequestCardProps) {
  return (
    <Paper p="md" component="section" aria-labelledby="request-title">
      <Stack gap="sm">
        <Title order={2} size="h4" id="request-title">
          Solicitar processamento
        </Title>
        <RangeFields
          start={start}
          end={end}
          onStartChange={onStartChange}
          onEndChange={onEndChange}
          maxDate={today}
        />
        <ScopeField value={scope} onChange={onScopeChange} />
        <Text size="sm" c="dimmed">
          Intervalo inclusivo. A dependência do fechamento anterior será validada antes da
          confirmação.
        </Text>
        <Group justify="flex-end">
          <Button
            onClick={onRequest}
            disabled={!isValidRange(start, end)}
            leftSection={<IconPlayerPlay size={16} stroke={1.5} />}
          >
            Solicitar processamento
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
