import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { PredecessorState, ProcessingChain, ProcessingPreview } from '@/api/contract';
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
  return state === 'PROCESSED' || state === 'PROCESSED_WITH_ISSUES'
    ? `${label} (${formatDate(predecessorDate).slice(0, 5)})`
    : label;
}

/** Unless processed or the zero state, the run fails on its first date (OQ-31 item 4). */
const blocks = (state: PredecessorState) =>
  state !== 'ZERO_STATE' && state !== 'PROCESSED' && state !== 'PROCESSED_WITH_ISSUES';

/**
 * What "Confirmar processamento" shows (§10.1, OQ-11, OQ-21): exactly [A, B], its days,
 * the scope, and the state before it for each chain in scope, warning when the run would fail
 * on its first date because the day before is not processed (OQ-31).
 */
export function PreviewSummary({ preview }: { preview: ProcessingPreview }) {
  const chains = chainsOf(preview.scope);
  const predecessor = formatDate(preview.predecessor_date);
  const stateOf = (chain: ProcessingChain) =>
    chain === 'CASH' ? preview.predecessor.cash : preview.predecessor.positions;
  const blocking = chains.filter((chain) => blocks(stateOf(chain)));
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
      {blocking.map((chain) => (
        <Alert
          key={chain}
          role="alert"
          color="yellow"
          variant="light"
          icon={<IconAlertTriangle size={18} />}
        >
          <Text size="sm">
            {stateOf(chain) === 'RUNNING'
              ? `O fechamento ${CHAIN_OF[chain]} de ${predecessor} ainda está em processamento. Se não terminar antes, este processamento falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia.`
              : `O fechamento ${CHAIN_OF[chain]} de ${predecessor} não foi processado. Este processamento falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia. Processe antes um intervalo que inclua esse dia.`}
          </Text>
        </Alert>
      ))}
    </Stack>
  );
}
