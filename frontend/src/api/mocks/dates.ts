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
