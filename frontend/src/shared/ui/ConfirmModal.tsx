import { Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import { useSubmitOnce } from '@/shared/form/useSubmitOnce';

import { ActionModal } from './ActionModal';
import { FormActions } from './FormActions';
import { MessageAlert } from './MessageAlert';
import { problemMessages } from './problemMessages';

interface ConfirmModalProps {
  opened: boolean;
  onClose: () => void;
  /** Runs the action; its promise settles when the action has finished (`mutateAsync`). */
  onConfirm: () => Promise<unknown>;
  title: string;
  /** What will happen, in pt-BR (counts, period, status). */
  children: ReactNode;
  confirmLabel: string;
  /** The action is running: both buttons wait and the modal cannot be closed. */
  loading?: boolean;
  /** The action failed: every problem+json message, field-bound ones included (OQ-15). */
  error?: unknown;
}

/**
 * Asks before an irreversible action (delete, cancel), which confirms in red; "Voltar" leaves
 * without acting. A double click confirms once (`useSubmitOnce`).
 */
export function ConfirmModal({
  opened,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel,
  loading = false,
  error,
}: ConfirmModalProps) {
  const once = useSubmitOnce();
  return (
    <ActionModal opened={opened} onClose={onClose} title={title} pending={loading} size="md">
      <Stack gap="md">
        <Text component="div" size="sm">
          {children}
        </Text>
        <MessageAlert messages={problemMessages(error)} />
        <FormActions
          submitLabel={confirmLabel}
          cancelLabel="Voltar"
          onCancel={onClose}
          onSubmit={() => {
            once(onConfirm);
          }}
          pending={loading}
          danger
        />
      </Stack>
    </ActionModal>
  );
}
