import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type {
  Freshness,
  PredecessorState,
  ProcessingChain,
  ProcessingPreview,
} from '@/api/contract';
import { formatDate, formatDays, formatPeriod } from '@/shared/format';
import { DATE_STATUS } from '@/shared/ui/dateStatus';
import { Field } from '@/shared/ui/Field';

import { CHAIN_OF, chainsOf, SCOPE_LABELS } from './scope';

const CHAIN_FIELD: Record<ProcessingChain, string> = {
  CASH: 'Estado anterior do caixa',
  POSITIONS: 'Estado anterior das posições',
};

/** The day before the range, per chain (OQ-26): its date status, or the chain's zero state. */
function stateText(state: PredecessorState, predecessorDate: string): string {
  if (state === 'ZERO_STATE') return 'Estado inicial (sem lançamentos anteriores)';
  const label = DATE_STATUS[state].label;
  return state === 'FRESH' || state === 'FRESH_WITH_ISSUES'
    ? `${label} em ${formatDate(predecessorDate).slice(0, 5)}`
    : label;
}

/** How a day before the range that is not current is described in the warning. */
const BEHIND_PHRASE: Partial<Record<Freshness, string>> = {
  STALE: 'está desatualizado',
  RUNNING: 'ainda está em processamento',
  FAILED: 'falhou no último processamento',
};

/** Unless current or the zero state, the run's dates are written stale (OQ-23 item 4). */
const isBehind = (state: PredecessorState) =>
  state !== 'ZERO_STATE' && state !== 'FRESH' && state !== 'FRESH_WITH_ISSUES';

/**
 * What "Confirmar processamento" shows (§10.1, OQ-11, OQ-21 draft): exactly [A, B], its days,
 * the scope, and the state before it for each chain in scope, warning when one is behind.
 */
export function PreviewSummary({ preview }: { preview: ProcessingPreview }) {
  const chains = chainsOf(preview.scope);
  const predecessor = formatDate(preview.predecessor_date);
  const stateOf = (chain: ProcessingChain) =>
    chain === 'CASH' ? preview.predecessor.cash : preview.predecessor.positions;
  const behind = chains.filter((chain) => isBehind(stateOf(chain)));
  return (
    <Stack gap="sm">
      <Field label="Período solicitado">{formatPeriod(preview.start_date, preview.end_date)}</Field>
      <Field label="Dias a processar">{formatDays(preview.total_days)}</Field>
      <Field label="Escopo">{SCOPE_LABELS[preview.scope]}</Field>
      {chains.map((chain) => (
        <Field key={chain} label={CHAIN_FIELD[chain]}>
          {stateText(stateOf(chain), preview.predecessor_date)}
        </Field>
      ))}
      {behind.map((chain) => (
        <Alert
          key={chain}
          role="alert"
          color="yellow"
          variant="light"
          icon={<IconAlertTriangle size={18} />}
        >
          <Text size="sm">
            {chain === 'CASH' && stateOf(chain) === 'NOT_PROCESSED'
              ? // OQ-22: cash is never carried from a day without published cash.
                `O caixa de ${predecessor} não foi processado: este processamento será recusado ao iniciar, sem publicar nenhum dia. Processe antes um intervalo que inclua esse dia.`
              : `${
                  stateOf(chain) === 'NOT_PROCESSED'
                    ? `O dia ${predecessor} ainda não foi processado para o cálculo das posições.`
                    : `O fechamento ${CHAIN_OF[chain]} de ${predecessor} ${BEHIND_PHRASE[stateOf(chain) as Freshness]}.`
                } O processamento será executado, mas os dias do intervalo aparecerão como desatualizados${
                  chain === 'POSITIONS' ? ', sem P&L,' : ''
                } e uma pendência pedirá o processamento de um intervalo anterior.`}
          </Text>
        </Alert>
      ))}
    </Stack>
  );
}
