import { SegmentedControl, Stack, Text, TextInput, type TextInputProps } from '@mantine/core';
import { useId } from 'react';

import type { InputKind } from '@/api/contract';

const KIND_LABEL: Record<InputKind, string> = { PU: 'PU', RATE: 'Taxa a.a.' };
const INPUT_LABEL: Record<InputKind, string> = { PU: 'PU', RATE: 'Taxa a.a. (%)' };

// OQ-3: a typed PU has at most 10 places; a typed rate at most 12 as a fraction, which is 10
// in the percent the user types. More places are rejected by the backend, never rounded.
const DESCRIPTION: Record<InputKind, string> = {
  PU: 'Até 10 casas decimais',
  RATE: 'Em % ao ano, até 10 casas decimais',
};

interface PriceInputProps {
  kind: InputKind;
  /** A new kind clears the typed value: a PU is never read as a rate. */
  onKindChange: (kind: InputKind) => void;
  /** The value input's props, e.g. `form.getInputProps('price')`. */
  inputProps: TextInputProps;
  placeholder: Record<InputKind, string>;
}

/**
 * PU **or** rate, as every price form takes it (§4.1, OQ-19 item 7): a toggle and one input.
 * The other value is computed by the backend on save; there is no preview.
 */
export function PriceInput({ kind, onKindChange, inputProps, placeholder }: PriceInputProps) {
  const labelId = useId();
  return (
    <>
      <Stack gap={6}>
        <Text size="sm" fw={500} id={labelId}>
          Forma de entrada
        </Text>
        <SegmentedControl
          aria-labelledby={labelId}
          fullWidth
          data={[
            { value: 'PU', label: KIND_LABEL.PU },
            { value: 'RATE', label: KIND_LABEL.RATE },
          ]}
          value={kind}
          onChange={(value) => {
            onKindChange(value);
          }}
        />
      </Stack>
      <TextInput
        label={INPUT_LABEL[kind]}
        description={DESCRIPTION[kind]}
        withAsterisk
        inputMode="decimal"
        placeholder={placeholder[kind]}
        {...inputProps}
      />
    </>
  );
}
