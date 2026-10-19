import type { ProcessingChain, ProcessingScope } from '@/api/contract';

// The two daily chains and the scope of a processing request (OQ-21), in pt-BR.

export const SCOPE_LABELS: Record<ProcessingScope, string> = {
  CASH: 'Caixa',
  POSITIONS: 'Posições',
  ALL: 'Tudo',
};

export const SCOPE_OPTIONS: { value: ProcessingScope; label: string }[] = [
  { value: 'CASH', label: SCOPE_LABELS.CASH },
  { value: 'POSITIONS', label: SCOPE_LABELS.POSITIONS },
  { value: 'ALL', label: SCOPE_LABELS.ALL },
];

/** The chain as a noun in a sentence: "do caixa", "das posições". */
export const CHAIN_OF: Record<ProcessingChain, string> = {
  CASH: 'do caixa',
  POSITIONS: 'das posições',
};

/** The chains a scope processes. */
export function chainsOf(scope: ProcessingScope): ProcessingChain[] {
  return scope === 'ALL' ? ['CASH', 'POSITIONS'] : [scope];
}

/** The scope's value in the URL (`escopo`), and back. */
const URL_VALUES: Record<ProcessingScope, string> = {
  CASH: 'caixa',
  POSITIONS: 'posicoes',
  ALL: 'tudo',
};

export const scopeToUrl = (scope: ProcessingScope) => URL_VALUES[scope];

export function scopeFromUrl(value: string | null): ProcessingScope | null {
  const found = Object.entries(URL_VALUES).find(([, v]) => v === value);
  return found ? (found[0] as ProcessingScope) : null;
}
