import { parsePtBrDecimal, percentToFraction } from '.';

describe('parsePtBrDecimal (form input → decimal string, no float)', () => {
  it('§12 reads Brazilian thousands dots and decimal comma', () => {
    expect(parsePtBrDecimal('1.234,56')).toBe('1234.56');
    expect(parsePtBrDecimal('1.500.000,00')).toBe('1500000.00');
    expect(parsePtBrDecimal('89.006,4625467350')).toBe('89006.4625467350');
  });

  it('§12 accepts digits without thousands separators and integers', () => {
    expect(parsePtBrDecimal('1234,56')).toBe('1234.56');
    expect(parsePtBrDecimal('50000')).toBe('50000');
    expect(parsePtBrDecimal('0,5')).toBe('0.5');
  });

  it('OQ-3 keeps every typed decimal, so the backend can reject too many places', () => {
    expect(parsePtBrDecimal('0,10000000000000')).toBe('0.10000000000000');
    // As a float this is 0.3: the trailing 1 would be lost. The string keeps it.
    expect(parsePtBrDecimal('0,3000000000000000001')).toBe('0.3000000000000000001');
  });

  it('§12 trims spaces, drops leading zeros of the integer part and keeps a sign', () => {
    expect(parsePtBrDecimal('  12,5 ')).toBe('12.5');
    expect(parsePtBrDecimal('007,10')).toBe('7.10');
    expect(parsePtBrDecimal('-1,5')).toBe('-1.5');
  });

  it('§12 writes zero without a sign', () => {
    expect(parsePtBrDecimal('-0')).toBe('0');
    expect(parsePtBrDecimal('-0,00')).toBe('0.00');
  });

  it.each([
    '',
    '   ',
    'abc',
    '1,2,3',
    '1.23,4',
    '12.34',
    '1..234',
    '.123',
    ',5',
    '12,',
    '1 234,56',
    '1e5',
    '+-1',
    '--1',
    'R$ 10',
    // A dot typed as the decimal point must not be read as thousands (1000× the value).
    '0.005',
    '0.125',
    '000.001,5',
  ])('§12 rejects invalid input %j', (input) => {
    expect(parsePtBrDecimal(input)).toBeNull();
  });
});

describe('percentToFraction (typed % → fraction sent to the API)', () => {
  it('§4.1 moves the decimal point two places, from the string', () => {
    expect(percentToFraction('10,45')).toBe('0.1045');
    expect(percentToFraction('10')).toBe('0.10');
    expect(percentToFraction('0,5')).toBe('0.005');
    expect(percentToFraction('100')).toBe('1.00');
    expect(percentToFraction('1.234,5')).toBe('12.345');
    expect(percentToFraction('9,3203413834')).toBe('0.093203413834');
  });

  it('§4.1 keeps a sign and every typed digit', () => {
    expect(percentToFraction('-1,5')).toBe('-0.015');
    expect(percentToFraction('0')).toBe('0.00');
    expect(percentToFraction('-0,00')).toBe('0.0000');
  });

  it('§4.1 rejects what parsePtBrDecimal rejects', () => {
    expect(percentToFraction('10,4,5')).toBeNull();
    expect(percentToFraction('')).toBeNull();
    expect(percentToFraction('10%')).toBeNull();
    expect(percentToFraction('0.125')).toBeNull();
  });
});
