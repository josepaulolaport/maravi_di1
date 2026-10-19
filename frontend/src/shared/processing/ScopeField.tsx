import { SegmentedControl, Stack, Text } from '@mantine/core';
import { useId } from 'react';

import type { ProcessingScope } from '@/api/contract';

import { SCOPE_OPTIONS } from './scope';

interface ScopeFieldProps {
  value: ProcessingScope;
  onChange: (scope: ProcessingScope) => void;
  disabled?: boolean;
  /** The API's message for `scope` (problem+json `errors[].field`, OQ-15). */
  error?: string | undefined;
}

/**
 * "Escopo" of a processing request (OQ-21 draft): Caixa, Posições or Tudo. The options form one
 * radio group named "Escopo", described by the API's error when there is one.
 */
export function ScopeField({ value, onChange, disabled = false, error }: ScopeFieldProps) {
  const labelId = useId();
  const errorId = useId();
  return (
    <Stack
      gap={6}
      role="radiogroup"
      aria-labelledby={labelId}
      {...(error ? { 'aria-describedby': errorId, 'aria-invalid': true } : {})}
    >
      <Text size="sm" fw={500} id={labelId}>
        Escopo
      </Text>
      <SegmentedControl
        data={SCOPE_OPTIONS}
        value={value}
        onChange={(next) => {
          onChange(next);
        }}
        disabled={disabled}
      />
      {error && (
        <Text size="xs" c="red" id={errorId}>
          {error}
        </Text>
      )}
    </Stack>
  );
}
