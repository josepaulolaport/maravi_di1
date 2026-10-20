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

/** The scope's text in the URL (`escopo`). */
export const SCOPE_URL: Record<ProcessingScope, string> = {
  CASH: 'caixa',
  POSITIONS: 'posicoes',
  ALL: 'tudo',
};
