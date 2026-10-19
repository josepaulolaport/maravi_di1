import { DateInput, type DateInputProps } from '@mantine/dates';
import { type SyntheticEvent, useState } from 'react';

import type { IsoDate } from '@/api/contract';
import { parsePtBrDate } from '@/shared/format';

import { FUTURE_DATE_MESSAGE } from './futureDate';

interface PastDateInputProps extends Omit<DateInputProps, 'onChange' | 'maxDate'> {
  /** Today in São Paulo (OQ-14); a typed date after it is refused with FUTURE_DATE's message. */
  today: IsoDate;
  /** The last accepted date, when earlier than today (a matured contract, OQ-1). */
  maxDate?: IsoDate | undefined;
  /** Shown for a typed date after `maxDate` but not after today. */
  limitMessage?: string | undefined;
  onChange?: ((value: IsoDate | null) => void) | undefined;
}

/**
 * A DD/MM/AAAA date input that refuses a typed date past its limit out loud (OQ-14, OQ-1).
 * Mantine's DateInput alone ignores a typed date after `maxDate` and keeps the previous one, so
 * a save (on blur, or Enter before any blur) could go out with a date the user did not type.
 * Here the date is dropped as soon as the text reads past the limit, and the field shows why
 * until another date is chosen.
 */
export function PastDateInput({
  today,
  maxDate = today,
  limitMessage,
  error,
  onBlur,
  onInput,
  onChange,
  ...props
}: PastDateInputProps) {
  const [refused, setRefused] = useState<string | null>(null);
  const check = (event: SyntheticEvent<HTMLInputElement>) => {
    const typed = parsePtBrDate(event.currentTarget.value);
    if (typed === null || typed <= maxDate) return;
    setRefused(typed > today ? FUTURE_DATE_MESSAGE : (limitMessage ?? FUTURE_DATE_MESSAGE));
    onChange?.(null);
  };
  return (
    <DateInput
      placeholder="DD/MM/AAAA"
      valueFormat="DD/MM/YYYY"
      dateParser={parsePtBrDate}
      {...props}
      maxDate={maxDate}
      error={refused ?? error}
      onChange={(value) => {
        setRefused(null);
        onChange?.(value);
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
