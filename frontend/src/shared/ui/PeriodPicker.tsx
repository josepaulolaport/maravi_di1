import { DatePickerInput, type DatesRangeValue } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import type { IsoDate } from '@/api/contract';

interface PeriodPickerProps {
  start: IsoDate;
  end: IsoDate;
  /** The last selectable day: today, or min(today, maturity) on a contract. */
  maxDate: IsoDate;
  onChange: (range: { start: IsoDate; end: IsoDate }) => void;
  /**
   * One click can close a one-day range. Lançamentos needs that; the contract calendar
   * keeps the two-click range.
   */
  allowSingleDateInRange?: boolean;
  /** Fixed width. Without it the field only has a minimum, so it can grow in a row. */
  w?: number;
}

/**
 * "Período": an inclusive date range. The picker keeps the half-picked range (first click)
 * as a draft; the period changes only once both ends are picked. A period set from outside
 * (the URL, a save) replaces the draft.
 */
export function PeriodPicker({
  start,
  end,
  maxDate,
  onChange,
  allowSingleDateInRange = false,
  w,
}: PeriodPickerProps) {
  const [draft, setDraft] = useState<DatesRangeValue<string>>([start, end]);
  const [synced, setSynced] = useState(`${start}|${end}`);
  if (synced !== `${start}|${end}`) {
    setSynced(`${start}|${end}`);
    setDraft([start, end]);
  }

  return (
    <DatePickerInput
      type="range"
      label="Período"
      value={draft}
      onChange={(value) => {
        setDraft(value);
        const [from, to] = value;
        if (from && to) onChange({ start: from, end: to });
      }}
      {...(allowSingleDateInRange ? { allowSingleDateInRange: true } : {})}
      maxDate={maxDate}
      valueFormat="DD/MM/YYYY"
      leftSection={<IconCalendar size={16} stroke={1.5} />}
      miw={260}
      {...(w !== undefined ? { w } : {})}
    />
  );
}
