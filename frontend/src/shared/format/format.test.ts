import {
  addDays,
  compareDecimal,
  decimalSign,
  displayedSign,
  formatDate,
  formatMoney,
  formatPu,
  formatQuantity,
  formatRate,
  formatSignedMoney,
  formatSignedQuantity,
  formatTime,
  isIsoDate,
  todayInSaoPaulo,
  UNAVAILABLE,
} from '.';

// Intl separates "R$" from the number with a no-break space.
const NBSP = ' ';

describe('number formatting (pt-BR, from decimal strings)', () => {
  it('§12 formats money with R$, dot thousands and comma decimals', () => {
    expect(formatMoney('1491965.8654717340')).toBe(`R$${NBSP}1.491.965,87`);
    expect(formatMoney('109090.91')).toBe(`R$${NBSP}109.090,91`);
  });

  it('OQ-3 rounds half up at the 2-decimal display, from the exact string', () => {
    expect(formatMoney('0.005')).toBe(`R$${NBSP}0,01`);
    expect(formatMoney('-0.005')).toBe(`-R$${NBSP}0,01`);
    // A float would lose this digit: 0.285 is 0.28499999… in binary.
    expect(formatMoney('0.285')).toBe(`R$${NBSP}0,29`);
  });

  it('§8.3 shows null as unavailable, never as zero', () => {
    expect(formatMoney(null)).toBe(UNAVAILABLE);
    expect(formatSignedMoney(undefined)).toBe('—');
    expect(formatPu(null)).toBe('—');
    expect(formatRate(null)).toBe('—');
    expect(formatQuantity(null)).toBe('—');
  });

  it('§8.1 signs P&L explicitly and leaves zero unsigned', () => {
    expect(formatSignedMoney('1220.1988777680')).toBe(`+R$${NBSP}1.220,20`);
    expect(formatSignedMoney('-9254.3334060340')).toBe(`-R$${NBSP}9.254,33`);
    expect(formatSignedMoney('0.0000000000')).toBe(`R$${NBSP}0,00`);
  });

  it('§4.1 formats PU with 2 decimals and the rate fraction as a percentage', () => {
    expect(formatPu('90909.0909090909')).toBe('90.909,09');
    expect(formatRate('0.10')).toBe('10,00%');
    expect(formatRate('0.093203413834')).toBe('9,32%');
    expect(formatRate('0')).toBe('0,00%');
  });

  it('formats quantities, signed when they are trades', () => {
    expect(formatQuantity(-5)).toBe('-5');
    expect(formatQuantity(1200)).toBe('1.200');
    expect(formatSignedQuantity(10)).toBe('+10');
    expect(formatSignedQuantity(-4)).toBe('-4');
  });

  it('§8.1 takes the colour sign from the rounded text, not the raw decimal', () => {
    const tiny = formatSignedMoney('-0.0042');
    expect(tiny).toBe(`R$${NBSP}0,00`);
    expect(displayedSign(tiny)).toBe(0);
    expect(displayedSign(formatSignedMoney('-0.01'))).toBe(-1);
    expect(displayedSign(formatSignedMoney('0.005'))).toBe(1);
  });

  it('reads the sign of a decimal string', () => {
    expect(decimalSign('-0.01')).toBe(-1);
    expect(decimalSign('0.0000')).toBe(0);
    expect(decimalSign('-0')).toBe(0);
    expect(decimalSign('12')).toBe(1);
    expect(decimalSign(null)).toBeNull();
  });

  it('compares decimal strings exactly, for sorting', () => {
    const values = ['10', '-9254.33', '0', '9.999999999999', '-0.5', '100.0', '9.99'];
    expect([...values].sort(compareDecimal)).toEqual([
      '-9254.33',
      '-0.5',
      '0',
      '9.99',
      '9.999999999999',
      '10',
      '100.0',
    ]);
    expect(compareDecimal('1.50', '1.5')).toBe(0);
    expect(compareDecimal('0012', '12')).toBe(0);
  });
});

describe('date formatting', () => {
  it('§12 shows dates as DD/MM/YYYY without time-zone shifts', () => {
    expect(formatDate('2026-10-15')).toBe('15/10/2026');
    expect(formatDate(null)).toBe('—');
    expect(formatTime('14:10:00')).toBe('14:10');
  });

  it('OQ-14 takes today from São Paulo, not from UTC', () => {
    // 01:30 UTC on 19/10 is still 22:30 on 18/10 in São Paulo (UTC−3).
    expect(todayInSaoPaulo(new Date('2026-10-19T01:30:00Z'))).toBe('2026-10-18');
  });

  it('adds calendar days across month ends and validates ISO dates', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-10-16', -29)).toBe('2026-09-17');
    expect(isIsoDate('2026-02-29')).toBe(false);
    expect(isIsoDate('2028-02-29')).toBe(true);
    expect(isIsoDate('16/10/2026')).toBe(false);
  });
});
