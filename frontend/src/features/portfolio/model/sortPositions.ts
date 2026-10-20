import type { PositionRow } from '@/api/contract';
import { compareDecimal } from '@/shared/format';

export const SORT_KEYS = [
  'asset_code',
  'maturity_date',
  'quantity',
  'average_entry_pu',
  'average_entry_rate',
  'reference_pu',
  'reference_rate',
  'financial_total',
  'position_pnl',
  'trades_pnl',
] as const;

export type SortKey = (typeof SORT_KEYS)[number];

/** The table's default order: by maturity, the nearest first. */
export const DEFAULT_SORT: Sort = { key: 'maturity_date', direction: 'asc' };

export interface Sort {
  key: SortKey;
  direction: 'asc' | 'desc';
}

type Compared = { kind: 'value'; value: number } | { kind: 'missing'; side: 'left' | 'right' };

/** Nulls are missing. Both missing compare equal, so the asset code breaks the tie. */
function compareNullable(
  left: string | null,
  right: string | null,
  compare: (left: string, right: string) => number,
): Compared {
  if (left === null && right === null) return { kind: 'value', value: 0 };
  if (left === null) return { kind: 'missing', side: 'left' };
  if (right === null) return { kind: 'missing', side: 'right' };
  return { kind: 'value', value: compare(left, right) };
}

/** One column, typed. A missing decimal or maturity is not a number and not text. */
function compareColumn(key: SortKey, a: PositionRow, b: PositionRow): Compared {
  switch (key) {
    case 'quantity':
      return { kind: 'value', value: a.quantity - b.quantity };
    case 'asset_code':
      return { kind: 'value', value: a.asset_code.localeCompare(b.asset_code, 'pt-BR') };
    case 'maturity_date':
      return compareNullable(a.maturity_date, b.maturity_date, (left, right) =>
        left.localeCompare(right, 'pt-BR'),
      );
    case 'average_entry_pu':
      return compareNullable(a.average_entry_pu, b.average_entry_pu, compareDecimal);
    case 'average_entry_rate':
      return compareNullable(a.average_entry_rate, b.average_entry_rate, compareDecimal);
    case 'reference_pu':
      return compareNullable(a.reference_pu, b.reference_pu, compareDecimal);
    case 'reference_rate':
      return compareNullable(a.reference_rate, b.reference_rate, compareDecimal);
    case 'financial_total':
      return compareNullable(a.financial_total, b.financial_total, compareDecimal);
    case 'position_pnl':
      return compareNullable(a.position_pnl, b.position_pnl, compareDecimal);
    case 'trades_pnl':
      return compareNullable(a.trades_pnl, b.trades_pnl, compareDecimal);
  }
}

/** Sorts rows by a column. Decimals compare exactly; unavailable (`null`) values go last. */
export function sortPositions(rows: PositionRow[], sort: Sort): PositionRow[] {
  const factor = sort.direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const compared = compareColumn(sort.key, a, b);
    // Missing stays last in either direction: it is not a value to reverse.
    if (compared.kind === 'missing') return compared.side === 'left' ? 1 : -1;
    return compared.value * factor || a.asset_code.localeCompare(b.asset_code);
  });
}
