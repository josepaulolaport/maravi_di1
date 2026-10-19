import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { ApiError } from '@/api/http';

/**
 * A failed action in a drawer or dialog (OQ-15): every problem+json message, except the one
 * per field in `shownOnFields` that the form shows on its own input.
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
  // A form shows one message per field (the first, as `ApiError.fieldErrors()` keeps); any
  // further message for that field stays here, so none is lost.
  const shown = new Set<string>();
  return errors
    .filter((e) => {
      if (e.field === null || !shownOnFields.includes(e.field) || shown.has(e.field)) return true;
      shown.add(e.field);
      return false;
    })
    .map((e) => e.message);
}
