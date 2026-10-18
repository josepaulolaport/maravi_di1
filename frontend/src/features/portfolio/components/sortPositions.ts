import type { PositionRow } from '@/api/contract';
import { compareDecimal } from '@/shared/format';

export type SortKey =
  | 'asset_code'
  | 'maturity_date'
  | 'quantity'
  | 'average_entry_pu'
  | 'average_entry_rate'
  | 'reference_pu'
  | 'reference_rate'
  | 'financial_total'
  | 'position_pnl'
  | 'trades_pnl';

export interface Sort {
  key: SortKey;
  direction: 'asc' | 'desc';
}

const DECIMAL_KEYS = new Set<SortKey>([
  'average_entry_pu',
  'average_entry_rate',
  'reference_pu',
  'reference_rate',
  'financial_total',
  'position_pnl',
  'trades_pnl',
]);

/** Sorts rows by a column. Decimals compare exactly; unavailable (`null`) values go last. */
export function sortPositions(rows: PositionRow[], sort: Sort): PositionRow[] {
  const factor = sort.direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const left = a[sort.key];
    const right = b[sort.key];
    if (left === null && right === null) return a.asset_code.localeCompare(b.asset_code);
    if (left === null) return 1;
    if (right === null) return -1;
    let result: number;
    if (sort.key === 'quantity') result = (left as number) - (right as number);
    else if (DECIMAL_KEYS.has(sort.key)) result = compareDecimal(left as string, right as string);
    else result = (left as string).localeCompare(right as string, 'pt-BR');
    return result * factor || a.asset_code.localeCompare(b.asset_code);
  });
}
