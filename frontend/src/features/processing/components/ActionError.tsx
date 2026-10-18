import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { ApiError } from '@/api/http';

/**
 * A failed action in a drawer or dialog: every problem+json message, field-bound ones too,
 * since the API's fields are not inputs here (OQ-15).
 */
export function ActionError({ error }: { error: unknown }) {
  const messages = errorMessages(error);
  if (messages.length === 0) return null;
  return (
    <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
      <Stack gap={4}>
        {messages.map((message) => (
          <Text key={message} size="sm">
            {message}
          </Text>
        ))}
      </Stack>
    </Alert>
  );
}

function errorMessages(error: unknown): string[] {
  if (error === undefined || error === null) return [];
  if (!(error instanceof ApiError)) return ['Ocorreu um erro inesperado. Tente novamente.'];
  const all = (error.problem.errors ?? []).map((e) => e.message);
  return all.length > 0 ? all : [error.message];
}
