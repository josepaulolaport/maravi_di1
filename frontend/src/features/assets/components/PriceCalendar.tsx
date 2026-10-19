import { ActionIcon, Group, Menu, Paper, Table, Text, Title, VisuallyHidden } from '@mantine/core';
import { IconDots, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';

import type { IsoDate, PriceSource, ReferencePriceDay } from '@/api/contract';
import { formatDate, formatPu, formatRate, UNAVAILABLE } from '@/shared/format';

import { countLabel } from '@/shared/format';
import type { CalendarRow } from './calendarData';

export const SOURCE_LABELS: Record<PriceSource, string> = { MANUAL: 'Manual', B3: 'B3' };

interface PriceCalendarProps {
  rows: CalendarRow[];
  onRegister: (date: IsoDate) => void;
  onCorrect: (date: IsoDate) => void;
  onRemove: (day: ReferencePriceDay) => void;
}

/**
 * "Calendário de preços de referência" (§11.2): every calendar day of the period, newest
 * first. A day shows its preferred observation (MANUAL over B3, §5) and its source; a day
 * without one shows "—" and is never filled from another day.
 */
export function PriceCalendar({ rows, onRegister, onCorrect, onRemove }: PriceCalendarProps) {
  const observed = rows.filter((row) => row.day !== null).length;
  return (
    <Paper>
      <Group justify="space-between" p="md">
        <Title order={2} size="h5" fw={500}>
          Calendário de preços de referência
        </Title>
        <Text size="xs" c="dimmed">
          {countLabel(rows.length, 'dia', 'dias')} ·{' '}
          {countLabel(observed, 'referência registrada', 'referências registradas')}
        </Text>
      </Group>
      {/* Any period fits: the rows scroll under a sticky header (§11.2). */}
      <Table.ScrollContainer minWidth={560} maxHeight={560}>
        <Table
          aria-label="Calendário de preços de referência"
          stickyHeader
          verticalSpacing="xs"
          horizontalSpacing="md"
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Data</Table.Th>
              <Table.Th ta="right">PU</Table.Th>
              <Table.Th ta="right">Taxa a.a.</Table.Th>
              <Table.Th>Fonte</Table.Th>
              <Table.Th w={56}>
                <VisuallyHidden>Ações</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map(({ date, day }) => {
              const label = formatDate(date);
              const preferred = day?.preferred;
              return (
                <Table.Tr key={date}>
                  <Table.Td>{label}</Table.Td>
                  <Table.Td ta="right">{preferred ? formatPu(preferred.pu) : UNAVAILABLE}</Table.Td>
                  <Table.Td ta="right">
                    {preferred ? formatRate(preferred.rate) : UNAVAILABLE}
                  </Table.Td>
                  <Table.Td>{preferred ? SOURCE_LABELS[preferred.source] : UNAVAILABLE}</Table.Td>
                  <Table.Td ta="right">
                    {day ? (
                      <Menu position="bottom-end" withinPortal>
                        <Menu.Target>
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            aria-label={`Ações de ${label}`}
                          >
                            <IconDots size={16} stroke={1.5} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item
                            leftSection={<IconPencil size={14} />}
                            onClick={() => {
                              onCorrect(date);
                            }}
                          >
                            Corrigir
                          </Menu.Item>
                          <Menu.Item
                            leftSection={<IconTrash size={14} />}
                            color="red"
                            onClick={() => {
                              onRemove(day);
                            }}
                          >
                            Remover
                          </Menu.Item>
                        </Menu.Dropdown>
                      </Menu>
                    ) : (
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        aria-label={`Registrar preço em ${label}`}
                        onClick={() => {
                          onRegister(date);
                        }}
                      >
                        <IconPlus size={16} stroke={1.5} />
                      </ActionIcon>
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  );
}
