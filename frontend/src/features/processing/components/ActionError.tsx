import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { problemMessages } from '@/shared/ui/problemMessages';

/** A failed action in a drawer or dialog: its problem+json messages (`problemMessages`). */
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
