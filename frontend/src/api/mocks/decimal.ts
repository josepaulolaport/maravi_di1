// Exact decimal addition for the fake backend only (decimals are strings end to end): the
// P&L series' range sum (OQ-31 item 8) is what the real backend computes with Decimal.

function scaled(value: string, places: number): bigint {
  const negative = value.startsWith('-');
  const [whole = '0', fraction = ''] = value.replace(/^[-+]/, '').split('.');
  const digits = BigInt(whole + fraction.padEnd(places, '0'));
  return negative ? -digits : digits;
}

const placesOf = (value: string) => value.split('.')[1]?.length ?? 0;

/** a + b, exact, with as many decimal places as the more precise of the two. */
export function addDecimal(a: string, b: string): string {
  const places = Math.max(placesOf(a), placesOf(b));
  const sum = scaled(a, places) + scaled(b, places);
  const negative = sum < 0n;
  const digits = (negative ? -sum : sum).toString().padStart(places + 1, '0');
  const whole = digits.slice(0, digits.length - places);
  const fraction = digits.slice(digits.length - places);
  return `${negative ? '-' : ''}${whole}${places > 0 ? `.${fraction}` : ''}`;
}
