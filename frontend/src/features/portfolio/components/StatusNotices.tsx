import { Alert, Anchor, Text } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { controlCenterLinks } from '@/app/paths';
import { formatDate } from '@/shared/format';

// A date with nothing published on either chain (§11.4). Stale or partly processed dates show
// no card: the two DataStatus badges tell the state (user, 2026-10-18), and missing figures
// read "—" with the asset marked in the table (§8.3).

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
