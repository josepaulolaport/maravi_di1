import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { ApiError } from '@/api/http';

/**
 * A failed action in a modal (OQ-15): every problem+json message, except those
 * bound to a field in `shownOnFields`, which the form shows on its own inputs.
 */
export function ActionError({
  error,
  shownOnFields = [],
}: {
  error: unknown;
  shownOnFields?: readonly string[];
}) {
  const messages = errorMessages(error, shownOnFields);
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

function errorMessages(error: unknown, shownOnFields: readonly string[]): string[] {
  if (error === undefined || error === null) return [];
  if (!(error instanceof ApiError)) return ['Ocorreu um erro inesperado. Tente novamente.'];
  const errors = error.problem.errors ?? [];
  if (errors.length === 0) return [error.message];
  return errors
    .filter((e) => !(e.field !== null && shownOnFields.includes(e.field)))
    .map((e) => e.message);
}
