import { Button, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';

import type { ProcessingDraft } from '@/shared/processing/ProcessingRequestModal';
import { isValidRange, RangeFields } from '@/shared/processing/RangeFields';
import { ScopeField } from '@/shared/processing/ScopeField';

import type { ControlCenterParams } from '../hooks/useControlCenterParams';

interface RequestCardProps {
  /** The range and scope, in the URL (a link from Carteira or a retry prefills them). */
  params: ControlCenterParams;
  /** Opens "Solicitar processamento" with the range and scope. */
  onRequest: (draft: ProcessingDraft) => void;
}

/**
 * "Solicitar processamento" (§10.1): an inclusive range and its scope (OQ-21: Caixa,
 * Posições or Tudo), previewed before it is queued.
 */
export function RequestCard({ params, onRequest }: RequestCardProps) {
  const { start, end, scope } = params;
  return (
    <Paper p="md" component="section" aria-labelledby="request-title">
      <Stack gap="sm">
        <Title order={2} size="h4" id="request-title">
          Solicitar processamento
        </Title>
        <RangeFields
          start={start}
          end={end}
          onStartChange={params.setStart}
          onEndChange={params.setEnd}
          maxDate={params.today}
        />
        <ScopeField value={scope} onChange={params.setScope} />
        <Text size="sm" c="dimmed">
          Intervalo inclusivo. A dependência do fechamento anterior será validada antes da
          confirmação.
        </Text>
        <Group justify="flex-end">
          <Button
            onClick={() => {
              if (start && end && isValidRange(start, end)) onRequest({ start, end, scope });
            }}
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
