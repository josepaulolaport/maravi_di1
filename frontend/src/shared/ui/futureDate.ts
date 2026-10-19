import { notifications } from '@mantine/notifications';
import { useEffect } from 'react';

import type { IsoDate } from '@/api/contract';
import { formatDate, isIsoDate } from '@/shared/format';

/** The API's FUTURE_DATE message (OQ-14), shown on a field when a future date is typed. */
export const FUTURE_DATE_MESSAGE = 'A data não pode ser posterior a hoje.';

/** A valid calendar date after today (São Paulo); dates are ISO strings, so they compare as text. */
export function isFutureDate(value: string | null | undefined, today: IsoDate): value is IsoDate {
  return isIsoDate(value) && value > today;
}

/**
 * A future date in a link (`?date=`, `?fim=`…) is not shown (OQ-14), but never ignored
 * silently: the user is told which date was refused. One notice per date (its id dedupes it).
 */
export function useFutureDateNotice(values: readonly (string | null)[], today: IsoDate) {
  const refused = values.filter((value) => isFutureDate(value, today)).join(',');
  useEffect(() => {
    if (!refused) return;
    for (const value of refused.split(',')) {
      notifications.show({
        id: `future-date-${value}`,
        color: 'yellow',
        message: `A data ${formatDate(value)} não pode ser posterior a hoje e foi ignorada.`,
      });
    }
  }, [refused]);
}
