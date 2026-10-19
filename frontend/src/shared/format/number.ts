import type { Decimal } from '@/api/contract';

// pt-BR formatting straight from decimal strings. `Intl.NumberFormat.format` accepts a string
// and formats it exactly (no float conversion); rounding is half away from zero, the same as
// the backend's ROUND_HALF_UP. The UI formats; it never calculates (CLAUDE.md §2).

/** Shown wherever a value is unavailable (`null`): never zero. */
export const UNAVAILABLE = '—';

type Formatter = Intl.NumberFormat;

const money: Formatter = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const signedMoney: Formatter = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  signDisplay: 'exceptZero',
});
const pu: Formatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
// 4 decimals (user decision, 2026-10-19): DI1 rates are quoted that way, and with 2 a rate of
// -99,9998% would read as the forbidden -100,00%.
const rate: Formatter = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const quantity: Formatter = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const signedQuantity: Formatter = new Intl.NumberFormat('pt-BR', {
  maximumFractionDigits: 0,
  signDisplay: 'exceptZero',
});

function format(formatter: Formatter, value: Decimal | null | undefined): string {
  if (value === null || value === undefined) return UNAVAILABLE;
  return formatter.format(value as Intl.StringNumericLiteral);
}

/** R$ 1.491.965,87 */
export const formatMoney = (value: Decimal | null | undefined) => format(money, value);

/** +R$ 1.220,20 / -R$ 9.254,33 / R$ 0,00: for P&L, where the sign matters. */
export const formatSignedMoney = (value: Decimal | null | undefined) => format(signedMoney, value);

/** 89.006,46: a PU with 2 decimals, as in the design. */
export const formatPu = (value: Decimal | null | undefined) => format(pu, value);

/** 10,0000%: an annual rate stored as a fraction (0.10). */
export const formatRate = (value: Decimal | null | undefined) => format(rate, value);

/** 10 / -5 */
export const formatQuantity = (value: number | null | undefined) =>
  value === null || value === undefined ? UNAVAILABLE : quantity.format(value);

/** +10 / -5: a trade's signed quantity. */
export const formatSignedQuantity = (value: number | null | undefined) =>
  value === null || value === undefined ? UNAVAILABLE : signedQuantity.format(value);

/**
 * The sign a formatted figure shows (+, - or none). Colour follows this, not the raw decimal,
 * so "-0.0042" shown as "R$ 0,00" is never painted red.
 */
export function displayedSign(text: string): -1 | 0 | 1 {
  if (text.startsWith('+')) return 1;
  if (text.startsWith('-')) return -1;
  return 0;
}

/** The sign of a decimal string (exact; used for sorting). */
export function decimalSign(value: Decimal | null | undefined): -1 | 0 | 1 | null {
  if (value === null || value === undefined) return null;
  if (/^-?0*(\.0*)?$/.test(value)) return 0;
  return value.startsWith('-') ? -1 : 1;
}

/**
 * Compares two decimal strings exactly (for sorting), without converting them to floats.
 * Returns a negative number, zero or a positive number.
 */
export function compareDecimal(a: Decimal, b: Decimal): number {
  const signA = decimalSign(a) ?? 0;
  const signB = decimalSign(b) ?? 0;
  if (signA !== signB) return signA - signB;
  if (signA === 0) return 0;
  const magnitude = compareMagnitude(a.replace(/^-/, ''), b.replace(/^-/, ''));
  return signA < 0 ? -magnitude : magnitude;
}

function compareMagnitude(a: string, b: string): number {
  const [intA = '0', fracA = ''] = a.split('.');
  const [intB = '0', fracB = ''] = b.split('.');
  const cleanA = intA.replace(/^0+(?=\d)/, '');
  const cleanB = intB.replace(/^0+(?=\d)/, '');
  if (cleanA.length !== cleanB.length) return cleanA.length - cleanB.length;
  if (cleanA !== cleanB) return cleanA < cleanB ? -1 : 1;
  const width = Math.max(fracA.length, fracB.length);
  const padA = fracA.padEnd(width, '0');
  const padB = fracB.padEnd(width, '0');
  if (padA === padB) return 0;
  return padA < padB ? -1 : 1;
}

/** A count of days in pt-BR: 1.000. */
export const formatDays = (days: number) => formatQuantity(days);
