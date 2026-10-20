import { DateInput, type DateInputProps } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';
import { type SyntheticEvent, useState } from 'react';

import type { IsoDate } from '@/api/contract';
import { parsePtBrDate } from '@/shared/format';
import { useToday } from '@/shared/hooks/useToday';
import { FUTURE_DATE_MESSAGE } from '@/shared/url/futureDate';

interface DateFieldProps extends Omit<DateInputProps, 'value' | 'onChange' | 'maxDate'> {
  /** Optional only so `form.getInputProps` fits; absent is no date. */
  value?: IsoDate | null;
  onChange: (value: IsoDate | null) => void;
  /**
   * The last accepted date: today by default (OQ-14), earlier for a matured contract (OQ-1);
   * `null` for no limit (a contract's maturity may be in the future).
   */
  maxDate?: IsoDate | null;
  /** Shown for a typed date after `maxDate` but not after today. */
  limitMessage?: string | undefined;
}

/**
 * Every single-date input: DD/MM/AAAA, typed or picked.
 * - A typed date past its limit is refused out loud (OQ-14, OQ-1). Mantine's DateInput alone
 *   ignores it and keeps the previous date, so a save (on blur, or Enter before any blur) could
 *   go out with a date the user did not type; here the date is dropped as soon as the text
 *   reads past the limit, and the field says why until another date is chosen.
 * - Mantine's DateInput keeps its own text and does not follow a value set from outside (a link,
 *   a prefill, a reset). Such a change remounts it, so the text shows the new date; a date typed
 *   or picked here does not, so typing keeps its focus.
 */
export function DateField({
  value = null,
  onChange,
  maxDate,
  limitMessage,
  error,
  onBlur,
  onInput,
  ...props
}: DateFieldProps) {
  const today = useToday();
  const limit = maxDate === undefined ? today : maxDate;
  const [refused, setRefused] = useState<string | null>(null);
  const [sync, setSync] = useState({ value, own: value, key: 0 });
  if (sync.value !== value) {
    setSync({ value, own: value, key: value === sync.own ? sync.key : sync.key + 1 });
  }
  const change = (next: IsoDate | null) => {
    setSync((current) => ({ ...current, own: next }));
    onChange(next);
  };
  const check = (event: SyntheticEvent<HTMLInputElement>) => {
    const typed = parsePtBrDate(event.currentTarget.value);
    if (typed === null || limit === null || typed <= limit) return;
    setRefused(typed > today ? FUTURE_DATE_MESSAGE : (limitMessage ?? FUTURE_DATE_MESSAGE));
    change(null);
  };
  return (
    <DateInput
      key={sync.key}
      placeholder="DD/MM/AAAA"
      valueFormat="DD/MM/YYYY"
      dateParser={parsePtBrDate}
      leftSection={<IconCalendar size={16} stroke={1.5} />}
      {...props}
      value={value}
      {...(limit !== null ? { maxDate: limit } : {})}
      error={refused ?? error}
      onChange={(next) => {
        setRefused(null);
        change(next);
      }}
      onInput={(event) => {
        check(event);
        onInput?.(event);
      }}
      onBlur={(event) => {
        check(event);
        onBlur?.(event);
      }}
    />
  );
}
