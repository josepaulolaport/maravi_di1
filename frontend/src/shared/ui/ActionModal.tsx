import { type MantineSize, Modal } from '@mantine/core';
import { type ReactNode, useState } from 'react';

interface ActionModalProps {
  opened: boolean;
  onClose: () => void;
  title: string;
  /** The modal's action is running: it cannot be closed, so its outcome is never lost. */
  pending?: boolean;
  size?: MantineSize;
  children: ReactNode;
}

/**
 * The modal of every form and confirmation. While its action runs it cannot be closed (no
 * Escape, outside click or close button). Its content is mounted from opening until the close
 * animation ends (so it never fades out empty), and every opening starts from a blank form.
 */
export function ActionModal({
  opened,
  onClose,
  title,
  pending = false,
  size = 'lg',
  children,
}: ActionModalProps) {
  const [mounted, setMounted] = useState(opened);
  if (opened && !mounted) setMounted(true);
  return (
    <Modal
      opened={opened}
      onClose={() => {
        if (!pending) onClose();
      }}
      title={title}
      centered
      size={size}
      closeOnEscape={!pending}
      closeOnClickOutside={!pending}
      withCloseButton={!pending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
      onExitTransitionEnd={() => {
        setMounted(false);
      }}
    >
      {mounted && children}
    </Modal>
  );
}
