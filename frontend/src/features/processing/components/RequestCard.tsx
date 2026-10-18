import { Button, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';

import type { IsoDate } from '@/api/contract';

import { isValidRange, RangeFields } from './RangeFields';

interface RequestCardProps {
  start: IsoDate | null;
  end: IsoDate | null;
  onStartChange: (date: IsoDate | null) => void;
  onEndChange: (date: IsoDate | null) => void;
  today: IsoDate;
  onRequest: () => void;
}

/** "Solicitar processamento" (§10.1): an inclusive range, previewed before it is queued. */
export function RequestCard({
  start,
  end,
  onStartChange,
  onEndChange,
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
