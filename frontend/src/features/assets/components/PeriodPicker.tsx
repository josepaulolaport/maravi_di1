import { DatePickerInput, type DatesRangeValue } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import type { IsoDate } from '@/api/contract';

interface PeriodPickerProps {
  start: IsoDate;
  end: IsoDate;
  /** The last selectable day: min(today, maturity). */
  maxDate: IsoDate;
  onChange: (range: { start: IsoDate; end: IsoDate }) => void;
}

/**
 * "Período" (§11.2): an inclusive date range. The picker keeps the half-picked range (first
 * click) as a draft; the period changes only once both ends are picked.
 */
export function PeriodPicker({ start, end, maxDate, onChange }: PeriodPickerProps) {
  const [draft, setDraft] = useState<DatesRangeValue<string>>([start, end]);
  // The period may change elsewhere (the URL, a save outside it): the draft follows it.
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
      maxDate={maxDate}
      // Keep the calendar open while picking even if the field scrolls out of view.
      popoverProps={{ hideDetached: false }}
      valueFormat="DD/MM/YYYY"
      leftSection={<IconCalendar size={16} stroke={1.5} />}
      miw={260}
    />
  );
}
