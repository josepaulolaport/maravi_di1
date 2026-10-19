import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { type ReactNode, useEffect, useRef } from 'react';

import { ApiError } from '@/api/http';

interface ConfirmModalProps {
  opened: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  /** What will happen, in pt-BR (counts, period, status). */
  children: ReactNode;
  confirmLabel: string;
  /** A destructive action (delete, cancel) confirms in red. */
  danger?: boolean;
  /** The action is running: both buttons wait. */
  loading?: boolean;
  /** The action failed: every problem+json message, field-bound ones included (OQ-15). */
  error?: unknown;
}

/** Asks before an irreversible action (delete, cancel); "Voltar" leaves without acting. */
export function ConfirmModal({
  opened,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel,
  danger = true,
  loading = false,
  error,
}: ConfirmModalProps) {
  // A double click must not run the action twice before the parent reports `loading`
  // (two cancel-and-replace requests would queue two jobs, §10.2). The guard opens again
  // once the attempt has finished (loading ended, or the dialog reopened) or has failed (a
  // new error). Clearing the error, which a parent may do as a retry starts, keeps it shut.
  const confirming = useRef(false);
  useEffect(() => {
    if (!loading) confirming.current = false;
  }, [loading, opened]);
  useEffect(() => {
    if (!loading && error !== undefined && error !== null) confirming.current = false;
  }, [loading, error]);
  const confirm = () => {
    if (loading || confirming.current) return;
    confirming.current = true;
    onConfirm();
  };
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      centered
      closeOnClickOutside={!loading}
      closeOnEscape={!loading}
      withCloseButton={!loading}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      <Stack gap="md">
        <Text component="div" size="sm">
          {children}
        </Text>
        {messages(error).length > 0 && (
          <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
            <Stack gap={4}>
              {messages(error).map((message) => (
                <Text key={message} size="sm">
                  {message}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={loading}>
            Voltar
          </Button>
          <Button {...(danger ? { color: 'red' } : {})} onClick={confirm} loading={loading}>
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** A dialog has no fields, so every message of the problem is shown in it. */
function messages(error: unknown): string[] {
  if (error === undefined || error === null) return [];
  if (!(error instanceof ApiError)) return ['Ocorreu um erro inesperado. Tente novamente.'];
  const all = (error.problem.errors ?? []).map((e) => e.message);
  return all.length > 0 ? all : [error.message];
}
