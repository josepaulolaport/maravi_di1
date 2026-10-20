import type { PriceSource, ReferencePrice } from '@/api/contract';
import { formatPu, formatRate } from '@/shared/format';

export const SOURCE_LABELS: Record<PriceSource, string> = { MANUAL: 'Manual', B3: 'B3' };

/** One observation of a date, as the removal lists it: "Manual: PU 89.250,31, taxa 9,8000%". */
export const observationLabel = (price: ReferencePrice) =>
  `${SOURCE_LABELS[price.source]}: PU ${formatPu(price.pu)}, taxa ${formatRate(price.rate)}`;
