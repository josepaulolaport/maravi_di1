import { Alert, Anchor, Stack, Text } from '@mantine/core';
import { IconAlertCircle, IconClockExclamation, IconInfoCircle } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { controlCenterLinks } from '@/app/paths';
import { formatDate } from '@/shared/format';

// The three states the screen must tell apart from "valid" (§8.3, §11.4): never processed,
// stale (inputs changed after publication) and incomplete (a required price is missing).
// Each offers the contextual path to Processamentos or Pendências.

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
        to={controlCenterLinks.processing({ start: date, end: date })}
        size="sm"
      >
        Solicitar processamento
      </Anchor>
    </Alert>
  );
}

interface PublishedNoticesProps {
  date: IsoDate;
  stale: boolean;
  incomplete: boolean;
}

export function PublishedNotices({ date, stale, incomplete }: PublishedNoticesProps) {
  if (!stale && !incomplete) return null;
  return (
    <Stack gap="xs">
      {stale && (
        <Alert
          color="yellow"
          variant="light"
          icon={<IconClockExclamation size={18} />}
          title="Resultados desatualizados"
        >
          <Text size="sm">
            Os dados de origem mudaram depois da publicação desta data, ou o dia anterior não estava
            atualizado quando ela foi processada. Os valores abaixo são os últimos publicados e
            podem não refletir os dados atuais.
          </Text>
          <Anchor
            component={Link}
            to={controlCenterLinks.processing({ start: date, end: date })}
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
