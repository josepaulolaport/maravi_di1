import { Group } from '@mantine/core';
import type { ReactNode } from 'react';

import type { IsoDate } from '@/api/contract';
import { DateField } from '@/shared/ui/DateField';

const INVALID_RANGE_MESSAGE = 'A data inicial deve ser anterior ou igual à data final.';

interface RangeFieldsProps {
  start: IsoDate | null;
  end: IsoDate | null;
  onStartChange: (date: IsoDate | null) => void;
  onEndChange: (date: IsoDate | null) => void;
  maxDate: IsoDate;
  /** API messages bound to `start_date` / `end_date` (OQ-15). */
  startError?: ReactNode;
  endError?: ReactNode;
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
        allowDeselect
        fixOnBlur
      />
      {/* On the field, so it is announced with it (aria-invalid, aria-describedby). */}
      <DateField
        label="Data final"
        value={end}
        onChange={onEndChange}
        maxDate={maxDate}
        error={reversed ? INVALID_RANGE_MESSAGE : endError}
        allowDeselect
        fixOnBlur
      />
    </Group>
  );
}
