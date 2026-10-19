import { Alert, Button, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { problemMessages } from './problemMessages';

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

/** A failed request: the API's pt-BR message (problem+json, OQ-15) and a retry. */
export function ErrorState({
  error,
  onRetry,
  title = 'Não foi possível carregar os dados',
}: ErrorStateProps) {
  // Every message, field-bound ones included: a read has no form to show them on (OQ-15).
  const messages = problemMessages(error);
  return (
    <Alert
      role="alert"
      color="red"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      title={title}
    >
      <Stack gap="xs" align="flex-start">
        {messages.map((message) => (
          <Text key={message} size="sm">
            {message}
          </Text>
        ))}
        {onRetry && (
          <Button size="xs" variant="white" color="red" onClick={onRetry}>
            Tentar novamente
          </Button>
        )}
      </Stack>
    </Alert>
  );
}
