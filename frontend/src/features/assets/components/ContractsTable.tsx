import { ActionIcon, Group, Menu, Table, Text } from '@mantine/core';
import { IconChevronRight, IconDots } from '@tabler/icons-react';
import { Link } from 'react-router';

import type { Instrument } from '@/api/contract';
import { assetLinks } from '@/app/paths';
import { formatDate, formatPu, formatRate, UNAVAILABLE } from '@/shared/format';
import { Figure } from '@/shared/ui/Figure';

/**
 * A product's contracts (§11.2). The PU and rate are the latest reference observation, always
 * shown with its own date, never as today's price (§5, OQ-19 item 5); none reads "—".
 */
interface ContractsTableProps {
  instruments: Instrument[];
  /** "Registrar preço" from a row's menu (OQ-48 item 1). */
  onRegisterPrice: (instrument: Instrument) => void;
  /** "Remover preço" from a row's menu (OQ-48 item 1). */
  onRemovePrice: (instrument: Instrument) => void;
}

export function ContractsTable({
  instruments,
  onRegisterPrice,
  onRemovePrice,
}: ContractsTableProps) {
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
            <Table.Th w={88} />
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
                <Table.Td ta="right">
                  <Figure text={last ? formatPu(last.pu) : UNAVAILABLE} />
                </Table.Td>
                <Table.Td ta="right">
                  <Figure text={last ? formatRate(last.rate) : UNAVAILABLE} />
                </Table.Td>
                <Table.Td>
                  <Figure text={last ? formatDate(last.reference_date) : UNAVAILABLE} />
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap" justify="flex-end">
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          aria-label={`Ações de ${instrument.code}`}
                        >
                          <IconDots size={16} stroke={1.5} />
                        </ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item
                          onClick={() => {
                            onRegisterPrice(instrument);
                          }}
                        >
                          Registrar preço
                        </Menu.Item>
                        <Menu.Item
                          color="red"
                          onClick={() => {
                            onRemovePrice(instrument);
                          }}
                        >
                          Remover preço
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                    <ActionIcon
                      component={Link}
                      to={assetLinks.contract(instrument.id)}
                      variant="subtle"
                      color="gray"
                      aria-label={`Abrir contrato ${instrument.code}`}
                    >
                      <IconChevronRight size={16} stroke={1.5} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
