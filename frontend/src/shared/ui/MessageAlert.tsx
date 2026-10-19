import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

/**
 * The red alert that lists a failed action's messages (OQ-15), announced to screen readers.
 * Renders nothing when there is none.
 */
export function MessageAlert({ messages }: { messages: readonly string[] }) {
  if (messages.length === 0) return null;
  return (
    <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
      <Stack gap={4}>
        {messages.map((message, index) => (
          <Text key={`${String(index)}-${message}`} size="sm">
            {message}
          </Text>
        ))}
      </Stack>
    </Alert>
  );
}
