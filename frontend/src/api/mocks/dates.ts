// Calendar arithmetic for the fake backend only (dates, never money).

const DAY_MS = 86_400_000;

function toUtc(date: string): number {
  return Date.parse(`${date}T00:00:00Z`);
}

export function addDays(date: string, amount: number): string {
  return new Date(toUtc(date) + amount * DAY_MS).toISOString().slice(0, 10);
}

/** Calendar days from `start` to `end` inclusive. */
export function daysInclusive(start: string, end: string): number {
  return (toUtc(end) - toUtc(start)) / DAY_MS + 1;
}

export function isIsoDate(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(toUtc(value)) &&
    new Date(toUtc(value)).toISOString().startsWith(value)
  );
}

/**
 * Today in São Paulo by the clock the app uses, so the fake backend never disagrees with the
 * screens about which dates are in the future (OQ-14). The fixtures' story is set on
 * MOCK_TODAY; the tests pin the clock there.
 */
export function today(now: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}
