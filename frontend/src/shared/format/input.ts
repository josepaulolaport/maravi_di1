import type { Decimal, InputKind } from '@/api/contract';

// Form input in pt-BR ("1.234,56") becomes the API's decimal string ("1234.56") by string
// manipulation only: no float ever holds the value, and every typed decimal is kept, so the
// backend can reject a value with too many places instead of the browser rounding it (OQ-3).

// Optional sign; an integer part either plain ("1234") or grouped in threes with dots
// ("1.234", never starting with 0, so "0.125" typed with a dot as the decimal point is
// rejected rather than read as 125); an optional comma and at least one decimal digit.
const PT_BR_DECIMAL = /^(-?)([1-9]\d{0,2}(?:\.\d{3})+|\d+)(?:,(\d+))?$/;

/** "1.234,56" → "1234.56"; `null` when the text is not a pt-BR decimal. */
export function parsePtBrDecimal(text: string): Decimal | null {
  const match = PT_BR_DECIMAL.exec(text.trim());
  if (!match) return null;
  const [, typedSign = '', grouped = '', fraction] = match;
  const integer = grouped.replaceAll('.', '').replace(/^0+(?=\d)/, '');
  // Zero has no sign: "-0,00" is sent as "0.00".
  const sign = /[1-9]/.test(`${integer}${fraction ?? ''}`) ? typedSign : '';
  return fraction === undefined ? `${sign}${integer}` : `${sign}${integer}.${fraction}`;
}

/**
 * A rate typed in percent ("10,45") → the fraction the API takes ("0.1045"), by moving the
 * decimal point two places left in the string. `null` when the text is not a pt-BR decimal.
 */
export function percentToFraction(text: string): Decimal | null {
  const decimal = parsePtBrDecimal(text);
  if (decimal === null) return null;
  const sign = decimal.startsWith('-') ? '-' : '';
  const [integer = '', fraction = ''] = decimal.replace(/^-/, '').split('.');
  const digits = integer.padStart(2, '0');
  const newInteger = digits.slice(0, -2).replace(/^0+(?=\d)/, '') || '0';
  return `${sign}${newInteger}.${digits.slice(-2)}${fraction}`;
}

/** The typed PU, or the typed percent as a fraction (10,45 → "0.1045"); `null` if invalid. */
export function typedPrice(kind: InputKind, text: string): Decimal | null {
  return kind === 'PU' ? parsePtBrDecimal(text) : percentToFraction(text);
}
