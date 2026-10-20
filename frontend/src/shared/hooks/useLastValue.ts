import { useState } from 'react';

/**
 * `value`, or the last non-null one while it is null: a modal keyed on data (a job, a date)
 * keeps showing it during its close animation instead of fading out empty.
 */
export function useLastValue<T>(value: T | null): T | null {
  const [last, setLast] = useState(value);
  if (value !== null && value !== last) setLast(value);
  return value ?? last;
}
