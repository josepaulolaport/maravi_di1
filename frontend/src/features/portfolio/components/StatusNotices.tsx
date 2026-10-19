import { Alert, Anchor, Stack, Text } from '@mantine/core';
import { IconAlertCircle, IconClockExclamation, IconInfoCircle } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { Freshness, IsoDate, ProcessingChain } from '@/api/contract';
import { controlCenterLinks } from '@/app/paths';
import { formatDate } from '@/shared/format';

// The states the screen must tell apart from "valid" (§8.3, §11.4), per chain since OQ-21
// (draft): never processed, stale (inputs changed after publication) and incomplete (a
// required price is missing). Each offers the contextual path to Processamentos or Pendências.

export function NotProcessedNotice({ date }: { date: IsoDate }) {
  return (
    <Alert
      color="gray"
      variant="light"
      icon={<IconInfoCircle size={18} />}
      title="Data não processada"
    >
      <Text size="sm">
        Os resultados de {formatDate(date)} ainda não foram calculados. A carteira só mostra dados
        publicados por um processamento.
      </Text>
      <Anchor
        component={Link}
        to={controlCenterLinks.processing({ start: date, end: date, scope: 'ALL' })}
        size="sm"
      >
        Solicitar processamento
      </Anchor>
    </Alert>
  );
}

type Chain = ProcessingChain;

const BEHIND_TITLE: Record<Chain, { stale: string; unprocessed: string }> = {
  CASH: { stale: 'Caixa desatualizado', unprocessed: 'Caixa não processado' },
  POSITIONS: { stale: 'Posições desatualizadas', unprocessed: 'Posições não processadas' },
};

interface ChainNoticesProps {
  date: IsoDate;
  cash: Freshness;
  positions: Freshness;
  incomplete: boolean;
}

/**
 * The states each chain must be told apart in (OQ-21 draft): cash and positions are processed
 * separately, so one can be current while the other is stale or never processed. Each notice
 * links to Processamentos prefilled with that chain's scope; when both are stale, with Tudo.
 */
export function ChainNotices({ date, cash, positions, incomplete }: ChainNoticesProps) {
  const statusOf = { CASH: cash, POSITIONS: positions };
  const chains: Chain[] = ['CASH', 'POSITIONS'];
  const stale = chains.filter((chain) => statusOf[chain] === 'STALE');
  const unprocessed = chains.filter((chain) => statusOf[chain] === 'NOT_PROCESSED');
  const range = { start: date, end: date };
  if (stale.length === 0 && unprocessed.length === 0 && !incomplete) return null;
  return (
    <Stack gap="xs">
      {unprocessed.map((chain) => (
        <Alert
          key={chain}
          color="gray"
          variant="light"
          icon={<IconInfoCircle size={18} />}
          title={BEHIND_TITLE[chain].unprocessed}
        >
          <Text size="sm">
            {chain === 'CASH'
              ? `O caixa de ${formatDate(date)} ainda não foi calculado; o patrimônio total fica indisponível.`
              : `As posições, a avaliação e o P&L de ${formatDate(date)} ainda não foram calculados; o patrimônio total fica indisponível.`}
          </Text>
          <Anchor
            component={Link}
            to={controlCenterLinks.processing({ ...range, scope: chain })}
            size="sm"
          >
            Solicitar processamento
          </Anchor>
        </Alert>
      ))}
      {stale.length > 0 && (
        <Alert
          color="yellow"
          variant="light"
          icon={<IconClockExclamation size={18} />}
          title={
            stale.length === 2
              ? 'Caixa e posições desatualizados'
              : BEHIND_TITLE[stale[0] as Chain].stale
          }
        >
          <Text size="sm">
            Os dados de origem mudaram depois da publicação desta data, ou o dia anterior não estava
            atualizado quando ela foi processada. Os valores abaixo são os últimos publicados e
            podem não refletir os dados atuais; o patrimônio total também fica desatualizado.
          </Text>
          <Anchor
            component={Link}
            to={controlCenterLinks.processing({
              ...range,
              scope: stale.length === 2 ? 'ALL' : (stale[0] as Chain),
            })}
            size="sm"
          >
            Ir para Processamentos
          </Anchor>
        </Alert>
      )}
      {incomplete && (
        <Alert
          color="red"
          variant="light"
          icon={<IconAlertCircle size={18} />}
          title="Resultados incompletos"
        >
          <Text size="sm">
            O valor de mercado ou o P&L de ao menos um ativo está indisponível nesta data. Os
            valores que dependem dele aparecem como indisponíveis (—), e os totais da carteira não
            estão completos. As pendências mostram o motivo.
          </Text>
          <Anchor component={Link} to={controlCenterLinks.issues()} size="sm">
            Ver pendências
          </Anchor>
        </Alert>
      )}
    </Stack>
  );
}
