import { formatDateTime, formatPeriod, formatProgress, parseDateInput, shortId } from './format';

describe('Central de Controle formatting (§11.1)', () => {
  it('§11.1 shows a timestamp in Brasília time, whatever its offset', () => {
    expect(formatDateTime('2026-10-16T18:35:00-03:00')).toBe('16/10/2026 18:35');
    expect(formatDateTime('2026-10-16T21:35:00Z')).toBe('16/10/2026 18:35');
  });

  it('§11.1 shows a missing timestamp as unavailable', () => {
    expect(formatDateTime(null)).toBe('—');
  });

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

  it('§11.1 reads a typed DD/MM/AAAA date as an ISO date, and nothing else', () => {
    expect(parseDateInput('17/10/2026')).toBe('2026-10-17');
    expect(parseDateInput(' 01/02/2026 ')).toBe('2026-02-01');
    expect(parseDateInput('31/02/2026')).toBeNull();
    expect(parseDateInput('2026-10-17')).toBeNull();
    expect(parseDateInput('17/10')).toBeNull();
  });
});
