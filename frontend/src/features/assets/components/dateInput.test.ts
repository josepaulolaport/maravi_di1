import { parsePtBrDate } from './dateInput';

describe('parsePtBrDate', () => {
  it('§11 reads a typed DD/MM/AAAA date as an ISO date', () => {
    expect(parsePtBrDate('02/01/2031')).toBe('2031-01-02');
    expect(parsePtBrDate(' 16/10/2026 ')).toBe('2026-10-16');
  });

  it('§11 rejects incomplete or impossible dates', () => {
    expect(parsePtBrDate('')).toBeNull();
    expect(parsePtBrDate('2/1/2031')).toBeNull();
    expect(parsePtBrDate('31/02/2027')).toBeNull();
    expect(parsePtBrDate('2031-01-02')).toBeNull();
  });
});
