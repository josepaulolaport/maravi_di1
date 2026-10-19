import { Group } from '@mantine/core';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import type { IsoDate } from '@/api/contract';

import { PastDateInput } from '@/shared/ui/PastDateInput';

const INVALID_RANGE_MESSAGE = 'A data inicial deve ser anterior ou igual à data final.';

/** A complete range with A ≤ B; dates are ISO strings, so they compare as text. */
export function isValidRange(start: IsoDate | null, end: IsoDate | null): boolean {
  return start !== null && end !== null && start <= end;
}

interface RangeFieldsProps {
  start: IsoDate | null;
  end: IsoDate | null;
  onStartChange: (date: IsoDate | null) => void;
  onEndChange: (date: IsoDate | null) => void;
  maxDate: IsoDate;
  /** API messages bound to `start_date` / `end_date` (OQ-15). */
  startError?: string | undefined;
  endError?: string | undefined;
}

/** "Data inicial" and "Data final", typed as DD/MM/AAAA or picked; never after today. */
export function RangeFields({
  start,
  end,
  onStartChange,
  onEndChange,
  maxDate,
  startError,
  endError,
}: RangeFieldsProps) {
  const reversed = start !== null && end !== null && start > end;
  return (
    <Group align="flex-start" gap="md" grow>
      <DateField
        label="Data inicial"
        value={start}
        onChange={onStartChange}
        maxDate={maxDate}
        error={startError}
      />
      {/* On the field, so it is announced with it (aria-invalid, aria-describedby). */}
      <DateField
        label="Data final"
        value={end}
        onChange={onEndChange}
        maxDate={maxDate}
        error={reversed ? INVALID_RANGE_MESSAGE : endError}
      />
    </Group>
  );
}

interface DateFieldProps {
  label: string;
  error?: string | undefined;
  value: IsoDate | null;
  onChange: (date: IsoDate | null) => void;
  maxDate: IsoDate;
}

/**
 * Mantine's DateInput keeps its own text and does not follow a controlled value set from
 * outside (a link, "Solicitar novo processamento"). Such a change remounts it, so the text
 * shows the new date; a date typed or picked here does not, so typing keeps its focus.
 */
function DateField({ label, value, onChange, maxDate, error }: DateFieldProps) {
  const [sync, setSync] = useState({ value, own: value, key: 0 });
  if (sync.value !== value) {
    setSync({ value, own: value, key: value === sync.own ? sync.key : sync.key + 1 });
  }
  return (
    <PastDateInput
      today={maxDate}
      key={sync.key}
      label={label}
      error={error}
      placeholder="DD/MM/AAAA"
      value={value}
      onChange={(next) => {
        setSync((current) => ({ ...current, own: next }));
        onChange(next);
      }}
      valueFormat="DD/MM/YYYY"
      maxDate={maxDate}
      allowDeselect
      fixOnBlur
      leftSection={<IconCalendar size={16} stroke={1.5} />}
    />
  );
}
