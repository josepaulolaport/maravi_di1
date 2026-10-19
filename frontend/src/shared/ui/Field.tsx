import { Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';

/** A labelled read-only value in a modal, exposed as a named group. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2} role="group" aria-label={label}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={500} component="div">
        {children}
      </Text>
    </Stack>
  );
}
