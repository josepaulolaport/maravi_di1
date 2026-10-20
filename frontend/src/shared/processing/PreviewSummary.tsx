import { Alert, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { PredecessorState, ProcessingChain, ProcessingPreview } from '@/api/contract';
import { formatDate, formatDayMonth, formatPeriod, formatQuantity } from '@/shared/format';
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
    ? `${label} (${formatDayMonth(predecessorDate)})`
    : label;
}

/** Unless processed or the zero state, the run fails on its first date (OQ-31 item 4). */
const blocks = (state: PredecessorState) =>
  state !== 'ZERO_STATE' && state !== 'PROCESSED' && state !== 'PROCESSED_WITH_ISSUES';

/**
 * What happens on the first date when `chain` fails there. On a Tudo run where the other chain
 * can run, only `chain` stops and the other goes on to the end (OQ-36); otherwise the run fails.
 */
function consequence(chain: ProcessingChain, otherGoesOn: boolean): string {
  const other: ProcessingChain = chain === 'CASH' ? 'POSITIONS' : 'CASH';
  return otherGoesOn
    ? `o fechamento ${CHAIN_OF[chain]} falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia; o fechamento ${CHAIN_OF[other]} seguirá até o fim do período.`
    : 'este processamento falhará no primeiro dia (dia anterior não processado), sem publicar nenhum dia.';
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * What "Confirmar processamento" shows (§10.1, OQ-11, OQ-21): exactly [A, B], its days,
 * the scope, and the state before it for each chain in scope, warning when a chain would fail
 * on its first date because the day before is not processed (OQ-31). The preview carries both
 * chains whatever the scope; only the scope's chains are shown and warned about (OQ-39).
 */
export function PreviewSummary({ preview }: { preview: ProcessingPreview }) {
  const chains = chainsOf(preview.scope);
  const predecessor = formatDate(preview.predecessor_date);
  const stateOf = (chain: ProcessingChain) =>
    chain === 'CASH' ? preview.predecessor.cash : preview.predecessor.positions;
  const blocking = chains.filter((chain) => blocks(stateOf(chain)));
  // A Tudo run with one chain blocked: the other still runs to the end (OQ-36).
  const otherGoesOn = preview.scope === 'ALL' && blocking.length === 1;
  return (
    <Stack gap="sm">
      <Field label="Período solicitado">{formatPeriod(preview.start_date, preview.end_date)}</Field>
      <Field label="Dias a processar">{formatQuantity(preview.total_days)}</Field>
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
              ? `O fechamento ${CHAIN_OF[chain]} de ${predecessor} ainda está em processamento. Se não terminar antes, ${consequence(chain, otherGoesOn)}`
              : `O fechamento ${CHAIN_OF[chain]} de ${predecessor} não foi processado. ${capitalized(consequence(chain, otherGoesOn))} Processe antes um intervalo que inclua esse dia.`}
          </Text>
        </Alert>
      ))}
    </Stack>
  );
}
