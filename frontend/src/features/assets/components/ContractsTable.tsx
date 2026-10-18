import { ActionIcon, Table, Text } from '@mantine/core';
import { IconChevronRight } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { Instrument } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { formatDate, formatPu, formatRate, UNAVAILABLE } from '@/shared/format';

/**
 * A product's contracts (§11.2). The PU and rate are the latest reference observation, always
 * shown with its own date, never as today's price (§5, OQ-19 item 5); none reads "—".
 */
export function ContractsTable({ instruments }: { instruments: Instrument[] }) {
  if (instruments.length === 0) {
    return (
      <Text size="sm" c="dimmed" px="md">
        Nenhum contrato encontrado.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table aria-label="Contratos" highlightOnHover verticalSpacing="sm" horizontalSpacing="md">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Contrato</Table.Th>
            <Table.Th>Vencimento</Table.Th>
            <Table.Th ta="right">Último PU</Table.Th>
            <Table.Th ta="right">Taxa a.a.</Table.Th>
            <Table.Th>Data ref.</Table.Th>
            <Table.Th w={48} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {instruments.map((instrument) => {
            const last = instrument.last_reference;
            return (
              <Table.Tr key={instrument.id}>
                <Table.Td>
                  <Text inherit fw={500}>
                    {instrument.code}
                  </Text>
                </Table.Td>
                <Table.Td>{formatDate(instrument.maturity_date)}</Table.Td>
                <Table.Td ta="right">{last ? formatPu(last.pu) : UNAVAILABLE}</Table.Td>
                <Table.Td ta="right">{last ? formatRate(last.rate) : UNAVAILABLE}</Table.Td>
                <Table.Td>{last ? formatDate(last.reference_date) : UNAVAILABLE}</Table.Td>
                <Table.Td>
                  <ActionIcon
                    component={Link}
                    to={assetLinks.contract(instrument.id)}
                    variant="subtle"
                    color="gray"
                    aria-label={`Abrir contrato ${instrument.code}`}
                  >
                    <IconChevronRight size={16} stroke={1.5} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
