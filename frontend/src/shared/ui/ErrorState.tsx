import { Alert, Button, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import { ApiError } from '@/api/http';

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
  const messages =
    error instanceof ApiError
      ? error.pageErrors()
      : ['Ocorreu um erro inesperado. Tente novamente.'];
  return (
    <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />} title={title}>
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
