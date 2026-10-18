import type { CashMovement, Decimal, IsoDate, IsoTime, Trade } from '@/api/contract';

// One table row of Lançamentos (§11.3): a trade or a cash movement. Instrument type and entry
// type are kept apart. Nothing is calculated here: a trade's figures are the backend's, and a
// movement's sign is only the direction its type gives (§6.2).

export type EntryType = 'BUY' | 'SELL' | 'DEPOSIT' | 'WITHDRAWAL';

export const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  BUY: 'Compra',
  SELL: 'Venda',
  DEPOSIT: 'Aporte',
  WITHDRAWAL: 'Retirada',
};

interface BaseEntry {
  /** Unique across both kinds: `trade:<id>` or `cash:<id>`. */
  key: string;
  id: string;
  date: IsoDate;
  entryType: EntryType;
  /** Cash effect: the backend's `cash_amount` for a trade; ±amount for a movement. */
  signedAmount: Decimal;
}

export interface TradeEntry extends BaseEntry {
  kind: 'trade';
  time: IsoTime;
  seq: number;
  instrumentTypeCode: string;
  assetCode: string;
  signedQuantity: number;
  pu: Decimal;
  rate: Decimal;
}

export interface CashEntry extends BaseEntry {
  kind: 'cash';
  createdAt: string;
}

export type LedgerEntry = TradeEntry | CashEntry;

export type SortDirection = 'asc' | 'desc';

function fromTrade(trade: Trade): TradeEntry {
  return {
    kind: 'trade',
    key: `trade:${trade.id}`,
    id: trade.id,
    date: trade.trade_date,
    time: trade.trade_time,
    seq: trade.seq,
    entryType: trade.signed_quantity > 0 ? 'BUY' : 'SELL',
    instrumentTypeCode: trade.instrument_type_code,
    assetCode: trade.asset_code,
    signedQuantity: trade.signed_quantity,
    pu: trade.execution_pu,
    rate: trade.execution_rate,
    signedAmount: trade.cash_amount,
  };
}

function fromMovement(movement: CashMovement): CashEntry {
  const deposit = movement.movement_type === 'DEPOSIT';
  return {
    kind: 'cash',
    key: `cash:${movement.id}`,
    id: movement.id,
    date: movement.movement_date,
    entryType: deposit ? 'DEPOSIT' : 'WITHDRAWAL',
    // The amount is always positive (§6.2); a retirada only shows a minus sign.
    signedAmount: deposit ? movement.amount : `-${movement.amount}`,
    createdAt: movement.created_at,
  };
}

export function mergeEntries(trades: Trade[], movements: CashMovement[]): LedgerEntry[] {
  return [...trades.map(fromTrade), ...movements.map(fromMovement)];
}

const compareText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/**
 * Newest first: by date; within a date, trades by (time, seq) as processed (§6.1), then cash
 * movements, which have no time (GAP-I-1), newest recorded first.
 */
function compareDescending(a: LedgerEntry, b: LedgerEntry): number {
  const byDate = compareText(b.date, a.date);
  if (byDate !== 0) return byDate;
  if (a.kind === 'trade' && b.kind === 'trade') {
    return compareText(b.time, a.time) || b.seq - a.seq;
  }
  if (a.kind === 'cash' && b.kind === 'cash') return compareText(b.createdAt, a.createdAt);
  return a.kind === 'trade' ? -1 : 1;
}

/** Ascending is the exact reverse of the default (descending) order. */
export function sortEntries(entries: LedgerEntry[], direction: SortDirection): LedgerEntry[] {
  const sorted = [...entries].sort(compareDescending);
  return direction === 'desc' ? sorted : sorted.reverse();
}
