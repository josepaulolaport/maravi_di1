import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { problemMessages } from '@/shared/ui/problemMessages';

/**
 * A failed action in a modal (OQ-15): its problem+json messages (`problemMessages`), except
 * those bound to a field in `shownOnFields`, which the form shows on its own inputs.
 */
export function ActionError({
  error,
  shownOnFields = [],
}: {
  error: unknown;
  shownOnFields?: readonly string[];
}) {
  const messages = problemMessages(error, shownOnFields);
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
