import { Button, Group } from '@mantine/core';

interface FormActionsProps {
  submitLabel: string;
  onCancel: () => void;
  /** The action is running: cancel waits and the submit button shows it. */
  pending: boolean;
  cancelLabel?: string;
  /** Without it the submit button submits its form; with it, the button runs it. */
  onSubmit?: () => void;
  disabled?: boolean;
  /** A destructive action (delete, cancel) is red. */
  danger?: boolean;
}

/** The footer of every form and confirmation: cancel, then the action. */
export function FormActions({
  submitLabel,
  onCancel,
  pending,
  cancelLabel = 'Cancelar',
  onSubmit,
  disabled = false,
  danger = false,
}: FormActionsProps) {
  return (
    <Group justify="flex-end" gap="sm">
      <Button variant="default" onClick={onCancel} disabled={pending}>
        {cancelLabel}
      </Button>
      <Button
        {...(onSubmit ? { onClick: onSubmit } : { type: 'submit' as const })}
        {...(danger ? { color: 'red' } : {})}
        loading={pending}
        disabled={disabled}
      >
        {submitLabel}
      </Button>
    </Group>
  );
}
