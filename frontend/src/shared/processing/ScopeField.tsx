import { SegmentedControl, Stack, Text } from '@mantine/core';
import { useId } from 'react';

import type { ProcessingScope } from '@/api/contract';

import { SCOPE_OPTIONS } from './scope';

interface ScopeFieldProps {
  value: ProcessingScope;
  onChange: (scope: ProcessingScope) => void;
  disabled?: boolean;
}

/** "Escopo" of a processing request (OQ-21 draft): Caixa, Posições or Tudo. */
export function ScopeField({ value, onChange, disabled = false }: ScopeFieldProps) {
  const labelId = useId();
  return (
    <Stack gap={6}>
      <Text size="sm" fw={500} id={labelId}>
        Escopo
      </Text>
      <SegmentedControl
        aria-labelledby={labelId}
        data={SCOPE_OPTIONS}
        value={value}
        onChange={(next) => {
          onChange(next);
        }}
        disabled={disabled}
      />
    </Stack>
  );
}
