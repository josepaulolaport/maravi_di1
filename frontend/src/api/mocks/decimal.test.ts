import { addDecimal } from './decimal';

describe('addDecimal (fake backend)', () => {
  it('adds decimal strings exactly, keeping the larger number of places', () => {
    expect(addDecimal('0', '-8034.1345282660')).toBe('-8034.1345282660');
    expect(addDecimal('0.1', '0.2')).toBe('0.3');
    expect(addDecimal('-394.7129232316', '1218.32')).toBe('823.6070767684');
    expect(addDecimal('-0.5', '0.25')).toBe('-0.25');
  });
});
