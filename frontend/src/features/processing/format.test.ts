import { formatPeriod, formatProgress, shortId } from './format';

describe('Central de Controle formatting (§11.1)', () => {
  it('§11.1 shows the inclusive period with both dates', () => {
    expect(formatPeriod('2026-10-14', '2026-10-16')).toBe('14/10/2026 a 16/10/2026');
  });

  it('§11.1 shows progress as "x / y dias"', () => {
    expect(formatProgress(2, 5)).toBe('2 / 5 dias');
    expect(formatProgress(0, 1)).toBe('0 / 1 dia');
    expect(formatProgress(999, 1000)).toBe('999 / 1.000 dias');
  });

  it('§11.1 shortens a request id to its first eight characters', () => {
    expect(shortId('7f000000-0000-4000-8000-000000000001')).toBe('7f000000');
  });
});
